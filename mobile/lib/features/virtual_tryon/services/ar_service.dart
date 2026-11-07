// mobile/lib/features/virtual_tryon/services/ar_service.dart
//
// CU17 - Vestidor Virtual (AR 2D).
//
// Envuelve la cámara del dispositivo y Google ML Kit Pose Detection.
// Expone, por cada frame de la cámara, los landmarks de pose que la
// pantalla necesita para posicionar la prenda sobre el cuerpo.
//
// Solo Android (alcance del proyecto): usa el formato NV21, el único
// que ML Kit interpreta de forma confiable en este SO, y compensa la
// rotación combinando la orientación del sensor con la orientación
// real del dispositivo (para cámara frontal se suma el ángulo, para
// trasera se resta, según la documentación del plugin).
//
// MODIFICADO (mejoras del vestidor):
// - Además de hombros y cadera, entrega codos (las mangas siguen los
//   brazos). Cada punto llega normalizado (0..1) sobre la imagen ya
//   enderezada y, con cámara frontal, espejada igual que la vista
//   previa; así la pantalla y la foto usan exactamente las mismas
//   coordenadas.
// - Cámara frontal o trasera (cambiarCamara).
// - capturarFotograma(): convierte el último cuadro de la cámara a una
//   imagen RGBA enderezada (y espejada en la frontal), para armar la
//   foto con la prenda encima sin desalinearla.

import 'dart:async';
import 'dart:isolate';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:camera/camera.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';


/// Puntos del cuerpo que usa el vestidor, normalizados (0..1) sobre la
/// imagen enderezada y espejada como la vista previa. null si ML Kit no
/// lo detectó con suficiente confianza.
class PoseFrame {
  final ui.Offset? hombroIzquierdo;
  final ui.Offset? hombroDerecho;
  final ui.Offset? codoIzquierdo;
  final ui.Offset? codoDerecho;
  final ui.Offset? caderaIzquierda;
  final ui.Offset? caderaDerecha;

  const PoseFrame({
    required this.hombroIzquierdo,
    required this.hombroDerecho,
    required this.codoIzquierdo,
    required this.codoDerecho,
    required this.caderaIzquierda,
    required this.caderaDerecha,
  });

  /// Hay suficientes puntos para dibujar la prenda (los dos hombros).
  bool get esValido => hombroIzquierdo != null && hombroDerecho != null;
}


/// Copia de un cuadro crudo NV21 (el plugin reutiliza el buffer original).
class _CuadroCrudo {
  final Uint8List bytes;
  final int ancho;
  final int alto;
  final int filaBytes;

  const _CuadroCrudo(this.bytes, this.ancho, this.alto, this.filaBytes);
}


/// Cuadro de la cámara listo para la foto: píxeles RGBA enderezados.
class Fotograma {
  final Uint8List rgba;
  final int ancho;
  final int alto;

  const Fotograma({required this.rgba, required this.ancho, required this.alto});
}


/// Administra el ciclo de vida de la cámara y el detector de poses.
///
/// Uso: inicializar() -> iniciarDeteccion(callback) -> ... -> liberar().
class ArService {
  CameraController? _cameraController;
  PoseDetector? _poseDetector;
  bool _procesandoFrame = false;
  List<CameraDescription> _camaras = [];
  CameraDescription? _camaraActual;
  void Function(PoseFrame)? _onFrame;
  Completer<_CuadroCrudo?>? _pedidoFotograma;

  CameraController? get cameraController => _cameraController;

  /// true si la cámara en uso es la frontal (la vista previa va espejada).
  bool get esFrontal => _camaraActual?.lensDirection == CameraLensDirection.front;

  /// true si el dispositivo tiene cámara frontal y trasera.
  bool get puedeCambiarCamara =>
      _camaras.any((c) => c.lensDirection == CameraLensDirection.front) &&
      _camaras.any((c) => c.lensDirection == CameraLensDirection.back);

  /// Ángulo (en grados) según la orientación física del dispositivo -
  /// tabla estándar usada por ML Kit para compensar la rotación.
  static const Map<DeviceOrientation, int> _orientaciones = {
    DeviceOrientation.portraitUp: 0,
    DeviceOrientation.landscapeLeft: 90,
    DeviceOrientation.portraitDown: 180,
    DeviceOrientation.landscapeRight: 270,
  };

  /// Confianza mínima de ML Kit para usar un punto del cuerpo.
  static const double _confianzaMinima = 0.5;

  /// Inicializa la cámara frontal (selfie) y el detector de poses.
  Future<void> inicializar() async {
    _camaras = await availableCameras();
    _poseDetector = PoseDetector(
      options: PoseDetectorOptions(mode: PoseDetectionMode.stream),
    );
    await _abrirCamara(CameraLensDirection.front);
  }

  Future<void> _abrirCamara(CameraLensDirection direccion) async {
    _camaraActual = _camaras.firstWhere(
      (c) => c.lensDirection == direccion,
      orElse: () => _camaras.first,
    );

    final controller = CameraController(
      _camaraActual!,
      ResolutionPreset.medium,
      enableAudio: false,
      // NV21 es el único formato que ML Kit interpreta de forma
      // confiable en Android.
      imageFormatGroup: ImageFormatGroup.nv21,
    );
    await controller.initialize();
    // La imagen siempre llega en vertical (evita la vista previa rotada
    // al usar startImageStream() en algunos Android).
    await controller.lockCaptureOrientation(DeviceOrientation.portraitUp);
    _cameraController = controller;
  }

  /// Empieza a procesar los frames de la cámara en vivo. Llama a
  /// [onFrame] cada vez que se detecta una pose en un frame nuevo.
  Future<void> iniciarDeteccion(void Function(PoseFrame) onFrame) async {
    _onFrame = onFrame;
    final controller = _cameraController;
    if (controller == null || _poseDetector == null) return;

    await controller.startImageStream((CameraImage imagen) async {
      // Pedido de foto: se entrega este cuadro tal cual.
      final pedido = _pedidoFotograma;
      if (pedido != null && !pedido.isCompleted) {
        _pedidoFotograma = null;
        // Se copian los bytes aquí mismo: el plugin reutiliza el buffer.
        pedido.complete(
          imagen.planes.length == 1
              ? _CuadroCrudo(
                  Uint8List.fromList(imagen.planes.first.bytes),
                  imagen.width,
                  imagen.height,
                  imagen.planes.first.bytesPerRow,
                )
              : null,
        );
      }

      // ML Kit procesa más lento que la cámara: mientras un cuadro está
      // en proceso, los siguientes se descartan.
      if (_procesandoFrame) return;
      _procesandoFrame = true;

      try {
        final rotacion = _rotacion();
        if (rotacion == null) return;
        final inputImage = _convertirImagen(imagen, rotacion);
        if (inputImage == null) return;

        final poses = await _poseDetector!.processImage(inputImage);
        if (poses.isEmpty) return;

        final landmarks = poses.first.landmarks;
        // Tamaño de la imagen ya enderezada (en 90/270 se invierten).
        final girada = rotacion == InputImageRotation.rotation90deg ||
            rotacion == InputImageRotation.rotation270deg;
        final ancho = (girada ? imagen.height : imagen.width).toDouble();
        final alto = (girada ? imagen.width : imagen.height).toDouble();

        ui.Offset? punto(PoseLandmarkType tipo) {
          final l = landmarks[tipo];
          if (l == null || l.likelihood < _confianzaMinima) return null;
          final nx = l.x / ancho;
          return ui.Offset(esFrontal ? 1 - nx : nx, l.y / alto);
        }

        _onFrame?.call(
          PoseFrame(
            hombroIzquierdo: punto(PoseLandmarkType.leftShoulder),
            hombroDerecho: punto(PoseLandmarkType.rightShoulder),
            codoIzquierdo: punto(PoseLandmarkType.leftElbow),
            codoDerecho: punto(PoseLandmarkType.rightElbow),
            caderaIzquierda: punto(PoseLandmarkType.leftHip),
            caderaDerecha: punto(PoseLandmarkType.rightHip),
          ),
        );
      } catch (_) {
        // Un cuadro que falla se ignora; el siguiente lo reemplaza.
      } finally {
        _procesandoFrame = false;
      }
    });
  }

  /// Cambia entre cámara frontal y trasera, manteniendo la detección.
  Future<void> cambiarCamara() async {
    if (!puedeCambiarCamara) return;
    final nueva = esFrontal ? CameraLensDirection.back : CameraLensDirection.front;
    final anterior = _cameraController;
    _cameraController = null;
    try {
      await anterior?.stopImageStream();
    } catch (_) {}
    await anterior?.dispose();
    await _abrirCamara(nueva);
    final onFrame = _onFrame;
    if (onFrame != null) {
      await iniciarDeteccion(onFrame);
    }
  }

  /// Rotación con la que hay que enderezar el cuadro de la cámara.
  InputImageRotation? _rotacion() {
    final controller = _cameraController;
    final camara = _camaraActual;
    if (controller == null || camara == null) return null;
    final gradosBase = _orientaciones[controller.value.deviceOrientation];
    if (gradosBase == null) return null;
    // Frontal: se SUMA el ángulo del sensor; trasera: se RESTA.
    final grados = esFrontal
        ? (camara.sensorOrientation + gradosBase) % 360
        : (camara.sensorOrientation - gradosBase + 360) % 360;
    return InputImageRotationValue.fromRawValue(grados);
  }

  /// Convierte un CameraImage NV21 al InputImage que espera ML Kit.
  InputImage? _convertirImagen(CameraImage imagen, InputImageRotation rotation) {
    final format = InputImageFormatValue.fromRawValue(imagen.format.raw);
    // Solo NV21 es confiable en Android.
    if (format == null || format != InputImageFormat.nv21) return null;
    if (imagen.planes.length != 1) return null;

    final plane = imagen.planes.first;
    return InputImage.fromBytes(
      bytes: plane.bytes,
      metadata: InputImageMetadata(
        size: ui.Size(imagen.width.toDouble(), imagen.height.toDouble()),
        rotation: rotation,
        format: format,
        bytesPerRow: plane.bytesPerRow,
      ),
    );
  }

  /// Toma el próximo cuadro de la cámara y lo devuelve como imagen RGBA
  /// enderezada (y espejada en la cámara frontal, igual que la vista
  /// previa). Devuelve null si la cámara no entregó un cuadro válido.
  Future<Fotograma?> capturarFotograma() async {
    if (_cameraController == null) return null;
    final rotacion = _rotacion();
    if (rotacion == null) return null;
    final frontal = esFrontal;

    final pedido = Completer<_CuadroCrudo?>();
    _pedidoFotograma = pedido;
    final cuadro = await pedido.future.timeout(const Duration(seconds: 3));
    if (cuadro == null) return null;

    return _convertirEnSegundoPlano(cuadro, rotacion, frontal);
  }

  /// La conversión se hace en otro hilo (Isolate) para no congelar la
  /// pantalla. Es estática para que la función enviada al otro hilo no
  /// arrastre el resto del servicio (cámara, detector).
  static Future<Fotograma> _convertirEnSegundoPlano(
    _CuadroCrudo cuadro,
    InputImageRotation rotacion,
    bool frontal,
  ) {
    final bytes = cuadro.bytes;
    final ancho = cuadro.ancho;
    final alto = cuadro.alto;
    final filaBytes = cuadro.filaBytes;
    return Isolate.run(
      () => _nv21ARgba(bytes, ancho, alto, filaBytes, rotacion, frontal),
    );
  }

  /// Convierte NV21 a RGBA, enderezando según [rotacion] y espejando si
  /// [espejar] (cámara frontal).
  static Fotograma _nv21ARgba(
    Uint8List nv21,
    int anchoCrudo,
    int altoCrudo,
    int filaBytes,
    InputImageRotation rotacion,
    bool espejar,
  ) {
    final girada = rotacion == InputImageRotation.rotation90deg ||
        rotacion == InputImageRotation.rotation270deg;
    final ancho = girada ? altoCrudo : anchoCrudo;
    final alto = girada ? anchoCrudo : altoCrudo;
    final rgba = Uint8List(ancho * alto * 4);
    final inicioUv = filaBytes * altoCrudo;

    for (var uy = 0; uy < alto; uy++) {
      for (var ux = 0; ux < ancho; ux++) {
        // Píxel del cuadro crudo que cae en (ux, uy) de la imagen derecha.
        var x = ux;
        var y = uy;
        if (rotacion == InputImageRotation.rotation90deg) {
          x = uy;
          y = altoCrudo - 1 - ux;
        } else if (rotacion == InputImageRotation.rotation270deg) {
          x = anchoCrudo - 1 - uy;
          y = ux;
        } else if (rotacion == InputImageRotation.rotation180deg) {
          x = anchoCrudo - 1 - ux;
          y = altoCrudo - 1 - uy;
        }

        final yValor = nv21[y * filaBytes + x];
        final iUv = inicioUv + (y >> 1) * filaBytes + (x & ~1);
        final v = (iUv < nv21.length ? nv21[iUv] : 128) - 128;
        final u = (iUv + 1 < nv21.length ? nv21[iUv + 1] : 128) - 128;

        final r = (yValor + 1.402 * v).round().clamp(0, 255).toInt();
        final g = (yValor - 0.344 * u - 0.714 * v).round().clamp(0, 255).toInt();
        final b = (yValor + 1.772 * u).round().clamp(0, 255).toInt();

        final destinoX = espejar ? ancho - 1 - ux : ux;
        final i = (uy * ancho + destinoX) * 4;
        rgba[i] = r;
        rgba[i + 1] = g;
        rgba[i + 2] = b;
        rgba[i + 3] = 255;
      }
    }
    return Fotograma(rgba: rgba, ancho: ancho, alto: alto);
  }

  /// Libera la cámara y el detector. Hay que llamarlo en el dispose()
  /// de la pantalla que use este servicio, o la cámara queda prendida.
  Future<void> liberar() async {
    final controller = _cameraController;
    _cameraController = null;
    try {
      await controller?.stopImageStream();
    } catch (_) {}
    await controller?.dispose();
    await _poseDetector?.close();
  }
}