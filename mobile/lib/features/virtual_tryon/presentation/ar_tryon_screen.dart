// mobile/lib/features/virtual_tryon/presentation/ar_tryon_screen.dart
//
// CU17 - Vestidor Virtual (AR 2D).
//
// Pantalla del vestidor virtual: cámara en vivo a pantalla completa con
// la prenda (PNG sin fondo) dibujada sobre el cuerpo según los puntos
// que detecta ML Kit Pose Detection.
//
// MODIFICADO (mejoras del vestidor):
// 1. Fluidez: ya no se redibuja toda la pantalla en cada cuadro; solo
//    la capa de la prenda (CustomPaint con ValueNotifier). Los puntos
//    del cuerpo se suavizan para que la prenda no tiemble.
// 2. Se mueve con los brazos: la prenda se dibuja como una malla que se
//    deforma; el torso va de los hombros a la cadera y cada manga gira
//    siguiendo la dirección hombro -> codo (movimientos suaves).
// 3. Talla: la prenda se dibuja más holgada o ajustada según la talla
//    elegida (M es la base). La cámara no mide el cuerpo en centímetros.
// 4. Cámara frontal o trasera.
// 5. Tomar foto: guarda en la galería (álbum "SmartLook") la imagen de la
//    cámara con la prenda puesta, tal como se ve en pantalla.
// 6. Recorte automático: se ignoran los bordes transparentes del PNG, así
//    la prenda sale del mismo tamaño aunque cada imagen tenga distinto
//    margen o tamaño de lienzo.
//
// Es una aproximación 2D (sin simulación de tela): funciona mejor con
// poleras, camisas y chaquetas fotografiadas de frente.

import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:gal/gal.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../../../core/network/api_client.dart';
import '../services/ar_service.dart';
import '../services/tryon_service.dart';


/// Tamaño de la prenda según la talla (M = base). Tallas desconocidas
/// (por ejemplo numéricas) se dibujan como M.
const Map<String, double> _factorPorTalla = {
  'XS': 0.90,
  'S': 0.95,
  'M': 1.00,
  'L': 1.06,
  'XL': 1.12,
  'XXL': 1.18,
};

double factorDeTalla(String? talla) {
  if (talla == null) return 1.0;
  return _factorPorTalla[talla.trim().toUpperCase()] ?? 1.0;
}


class ArTryOnScreen extends StatefulWidget {
  final int productoId;
  final String? overlayImageUrl;
  final String nombreProducto;
  // NUEVO: talla de la variante elegida (ajusta el tamaño de la prenda).
  final String? talla;

  const ArTryOnScreen({
    super.key,
    required this.productoId,
    required this.overlayImageUrl,
    required this.nombreProducto,
    this.talla,
  });

  @override
  State<ArTryOnScreen> createState() => _ArTryOnScreenState();
}

class _ArTryOnScreenState extends State<ArTryOnScreen> {
  final ArService _arService = ArService();
  late final TryonService _tryonService;

  // Solo esta capa se redibuja en cada cuadro (no toda la pantalla).
  final ValueNotifier<PoseFrame?> _pose = ValueNotifier<PoseFrame?>(null);
  final _Suavizador _suavizador = _Suavizador();
  DateTime _ultimaDeteccion = DateTime.fromMillisecondsSinceEpoch(0);
  Timer? _vigilante;

  ui.Image? _imagenPrenda;
  // NUEVO: parte de la imagen donde está la prenda (sin bordes transparentes).
  Rect? _recortePrenda;
  ImageStream? _streamPrenda;
  ImageStreamListener? _listenerPrenda;

  bool _cargando = true;
  bool _cambiandoCamara = false;
  bool _guardandoFoto = false;
  String? _error;

  double get _factor => factorDeTalla(widget.talla);

  @override
  void initState() {
    super.initState();
    _tryonService = TryonService(apiClient: context.read<ApiClient>());
    _cargarPrenda();
    _inicializarTodo();
    // Si deja de detectarse a la persona, la prenda se oculta.
    _vigilante = Timer.periodic(const Duration(milliseconds: 300), (_) {
      final sinPose = DateTime.now().difference(_ultimaDeteccion).inMilliseconds > 800;
      if (sinPose && _pose.value != null) {
        _pose.value = null;
        _suavizador.reiniciar();
      }
    });
  }

  /// Descarga la imagen de la prenda una sola vez (con caché).
  void _cargarPrenda() {
    final url = widget.overlayImageUrl;
    if (url == null || url.isEmpty) return;
    final stream = CachedNetworkImageProvider(url).resolve(ImageConfiguration.empty);
    final listener = ImageStreamListener(
      (info, _) => _prepararPrenda(info.image),
      onError: (_, __) {},
    );
    stream.addListener(listener);
    _streamPrenda = stream;
    _listenerPrenda = listener;
  }

  /// Calcula el recorte sin bordes transparentes antes de mostrar la prenda.
  Future<void> _prepararPrenda(ui.Image imagen) async {
    Rect recorte = Rect.fromLTWH(0, 0, imagen.width.toDouble(), imagen.height.toDouble());
    try {
      recorte = await recorteSinTransparencia(imagen);
    } catch (_) {
      // Si no se puede analizar, se usa la imagen completa.
    }
    if (!mounted) return;
    setState(() {
      _imagenPrenda = imagen;
      _recortePrenda = recorte;
    });
  }

  /// Pide el permiso de cámara, inicializa la cámara y arranca la
  /// detección. También registra la sesión en el backend (sin bloquear
  /// la pantalla si esa llamada falla).
  Future<void> _inicializarTodo() async {
    final estadoPermiso = await Permission.camera.request();
    if (!estadoPermiso.isGranted) {
      setState(() {
        _cargando = false;
        _error = 'Se necesita el permiso de cámara para usar el vestidor virtual.';
      });
      return;
    }

    try {
      await _arService.inicializar();
      await _arService.iniciarDeteccion(_alDetectar);
      _tryonService.registrarSesion(widget.productoId).catchError((_) {});
      if (mounted) setState(() => _cargando = false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _cargando = false;
          _error = 'No se pudo inicializar la cámara: $e';
        });
      }
    }
  }

  void _alDetectar(PoseFrame frame) {
    // Puede llegar un cuadro después de cerrar la pantalla.
    if (!mounted || !frame.esValido) return;
    _ultimaDeteccion = DateTime.now();
    _pose.value = _suavizador.suavizar(frame);
  }

  Future<void> _cambiarCamara() async {
    if (_cambiandoCamara) return;
    setState(() => _cambiandoCamara = true);
    _pose.value = null;
    _suavizador.reiniciar();
    try {
      await _arService.cambiarCamara();
    } catch (_) {
      _mostrarMensaje('No se pudo cambiar de cámara.');
    }
    if (mounted) setState(() => _cambiandoCamara = false);
  }

  /// Arma la foto (cuadro de la cámara + prenda en la misma posición que
  /// en pantalla) y la guarda en la galería.
  Future<void> _tomarFoto() async {
    if (_guardandoFoto) return;
    setState(() => _guardandoFoto = true);
    final poseActual = _pose.value;
    final prenda = _imagenPrenda;

    try {
      final fotograma = await _arService.capturarFotograma();
      if (fotograma == null) {
        _mostrarMensaje('No se pudo tomar la foto.');
        return;
      }

      final base = await _decodificar(fotograma);
      final ancho = fotograma.ancho.toDouble();
      final alto = fotograma.alto.toDouble();

      final recorder = ui.PictureRecorder();
      final canvas = Canvas(recorder);
      canvas.drawImage(base, Offset.zero, Paint());
      if (prenda != null && poseActual != null && poseActual.esValido) {
        dibujarPrenda(
          canvas,
          poseActual,
          prenda,
          _recortePrenda,
          Rect.fromLTWH(0, 0, ancho, alto),
          _factor,
        );
      }
      final imagenFinal =
          await recorder.endRecording().toImage(fotograma.ancho, fotograma.alto);
      final datos = await imagenFinal.toByteData(format: ui.ImageByteFormat.png);
      if (datos == null) {
        _mostrarMensaje('No se pudo tomar la foto.');
        return;
      }

      final archivo = File(
        '${Directory.systemTemp.path}/smartlook_${DateTime.now().millisecondsSinceEpoch}.png',
      );
      await archivo.writeAsBytes(datos.buffer.asUint8List());

      if (!await Gal.hasAccess(toAlbum: true)) {
        await Gal.requestAccess(toAlbum: true);
      }
      await Gal.putImage(archivo.path, album: 'SmartLook');
      _mostrarMensaje('Foto guardada en tu galería (álbum SmartLook).');
    } on GalException catch (e) {
      _mostrarMensaje(e.type.message);
    } catch (_) {
      _mostrarMensaje('No se pudo tomar la foto.');
    } finally {
      if (mounted) setState(() => _guardandoFoto = false);
    }
  }

  Future<ui.Image> _decodificar(Fotograma fotograma) {
    final completer = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      fotograma.rgba,
      fotograma.ancho,
      fotograma.alto,
      ui.PixelFormat.rgba8888,
      completer.complete,
    );
    return completer.future;
  }

  void _mostrarMensaje(String texto) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto)));
  }

  @override
  void dispose() {
    _vigilante?.cancel();
    final listener = _listenerPrenda;
    if (listener != null) _streamPrenda?.removeListener(listener);
    _arService.liberar();
    _pose.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: Text('Probando: ${widget.nombreProducto}'),
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: Colors.white),
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              : _construirVestidor(),
    );
  }

  Widget _construirVestidor() {
    final controller = _arService.cameraController;
    if (_cambiandoCamara || controller == null || !controller.value.isInitialized) {
      return const Center(child: CircularProgressIndicator());
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final anchoPantalla = constraints.maxWidth;
        final altoPantalla = constraints.maxHeight;

        // Proporción real de la cámara en vertical (previewSize viene en
        // horizontal). La caja se agranda hasta CUBRIR la pantalla y se
        // recorta lo que sobra.
        final previewSize = controller.value.previewSize;
        final aspecto = previewSize == null || previewSize.width == 0
            ? 3 / 4
            : previewSize.height / previewSize.width;
        double boxAncho = anchoPantalla;
        double boxAlto = boxAncho / aspecto;
        if (boxAlto < altoPantalla) {
          boxAlto = altoPantalla;
          boxAncho = boxAlto * aspecto;
        }
        final area = Rect.fromLTWH(
          (anchoPantalla - boxAncho) / 2,
          (altoPantalla - boxAlto) / 2,
          boxAncho,
          boxAlto,
        );

        return Stack(
          fit: StackFit.expand,
          children: [
            ClipRect(
              child: OverflowBox(
                maxWidth: boxAncho,
                maxHeight: boxAlto,
                child: SizedBox(
                  width: boxAncho,
                  height: boxAlto,
                  child: CameraPreview(controller),
                ),
              ),
            ),
            if (_imagenPrenda != null)
              CustomPaint(
                painter: _PrendaPainter(
                  pose: _pose,
                  imagen: _imagenPrenda!,
                  recorte: _recortePrenda,
                  area: area,
                  factor: _factor,
                ),
              ),
            _construirAyuda(),
            _construirControles(),
          ],
        );
      },
    );
  }

  /// Mensaje mientras no se detecta a la persona.
  Widget _construirAyuda() {
    return ValueListenableBuilder<PoseFrame?>(
      valueListenable: _pose,
      builder: (context, pose, _) {
        if (pose != null) return const SizedBox.shrink();
        return Align(
          alignment: const Alignment(0, -0.85),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.black54,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              _imagenPrenda == null
                  ? 'Cargando la prenda...'
                  : 'Ponte de frente y que se vean tus hombros',
              style: const TextStyle(color: Colors.white),
            ),
          ),
        );
      },
    );
  }

  /// Barra inferior: talla, botón de foto y cambio de cámara.
  Widget _construirControles() {
    return Positioned(
      left: 0,
      right: 0,
      bottom: 24,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          Container(
            width: 72,
            padding: const EdgeInsets.symmetric(vertical: 8),
            decoration: BoxDecoration(
              color: Colors.black54,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              widget.talla == null ? 'Talla -' : 'Talla ${widget.talla}',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
            ),
          ),
          GestureDetector(
            onTap: _guardandoFoto ? null : _tomarFoto,
            child: Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white,
                border: Border.all(color: Colors.white54, width: 5),
              ),
              child: _guardandoFoto
                  ? const Padding(
                      padding: EdgeInsets.all(20),
                      child: CircularProgressIndicator(strokeWidth: 3),
                    )
                  : const Icon(Icons.camera_alt, color: Colors.black87, size: 30),
            ),
          ),
          SizedBox(
            width: 72,
            child: _arService.puedeCambiarCamara
                ? IconButton(
                    tooltip: 'Cambiar cámara',
                    iconSize: 32,
                    color: Colors.white,
                    style: IconButton.styleFrom(backgroundColor: Colors.black54),
                    onPressed: _cambiandoCamara ? null : _cambiarCamara,
                    icon: const Icon(Icons.cameraswitch),
                  )
                : const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }
}


/// Suaviza los puntos del cuerpo entre cuadros (promedio móvil) para que
/// la prenda no tiemble. Si un codo deja de verse un momento, se mantiene
/// el último conocido.
class _Suavizador {
  // 0..1: más alto = sigue más rápido el movimiento, más bajo = más suave.
  static const double _alfa = 0.45;
  PoseFrame? _ultimo;

  PoseFrame suavizar(PoseFrame nuevo) {
    final anterior = _ultimo;
    if (anterior == null) {
      _ultimo = nuevo;
      return nuevo;
    }

    Offset? mezclar(Offset? previo, Offset? actual) {
      if (actual == null) return previo;
      if (previo == null) return actual;
      return Offset.lerp(previo, actual, _alfa);
    }

    final resultado = PoseFrame(
      hombroIzquierdo: mezclar(anterior.hombroIzquierdo, nuevo.hombroIzquierdo),
      hombroDerecho: mezclar(anterior.hombroDerecho, nuevo.hombroDerecho),
      codoIzquierdo: mezclar(anterior.codoIzquierdo, nuevo.codoIzquierdo),
      codoDerecho: mezclar(anterior.codoDerecho, nuevo.codoDerecho),
      caderaIzquierda: mezclar(anterior.caderaIzquierda, nuevo.caderaIzquierda),
      caderaDerecha: mezclar(anterior.caderaDerecha, nuevo.caderaDerecha),
    );
    _ultimo = resultado;
    return resultado;
  }

  void reiniciar() => _ultimo = null;
}


/// Capa de la prenda: se redibuja sola cada vez que cambia la pose.
class _PrendaPainter extends CustomPainter {
  final ValueListenable<PoseFrame?> pose;
  final ui.Image imagen;
  final Rect? recorte;
  final Rect area;
  final double factor;

  _PrendaPainter({
    required this.pose,
    required this.imagen,
    required this.recorte,
    required this.area,
    required this.factor,
  }) : super(repaint: pose);

  @override
  void paint(Canvas canvas, Size size) {
    final frame = pose.value;
    if (frame == null || !frame.esValido) return;
    dibujarPrenda(canvas, frame, imagen, recorte, area, factor);
  }

  @override
  bool shouldRepaint(covariant _PrendaPainter old) =>
      old.imagen != imagen ||
      old.recorte != recorte ||
      old.area != area ||
      old.factor != factor;
}


/// NUEVO: rectángulo (en píxeles) donde está la prenda dentro del PNG,
/// ignorando los bordes transparentes. Así una imagen con mucho margen o
/// un lienzo más grande se dibuja del mismo tamaño que las demás.
Future<Rect> recorteSinTransparencia(ui.Image imagen) async {
  final datos = await imagen.toByteData(format: ui.ImageByteFormat.rawRgba);
  final completo = Rect.fromLTWH(0, 0, imagen.width.toDouble(), imagen.height.toDouble());
  if (datos == null) return completo;
  final bytes = datos.buffer.asUint8List();
  final ancho = imagen.width;
  final alto = imagen.height;
  // El recorrido de píxeles se hace en otro hilo para no trabar la pantalla.
  final limites = await Isolate.run(() => _limitesOpacos(bytes, ancho, alto));
  if (limites == null) return completo;
  return Rect.fromLTRB(
    limites[0].toDouble(),
    limites[1].toDouble(),
    limites[2].toDouble() + 1,
    limites[3].toDouble() + 1,
  );
}

/// Devuelve [izquierda, arriba, derecha, abajo] de los píxeles visibles
/// (alfa mayor a 20), o null si la imagen es toda transparente.
List<int>? _limitesOpacos(Uint8List rgba, int ancho, int alto) {
  var izquierda = ancho;
  var arriba = alto;
  var derecha = -1;
  var abajo = -1;
  for (var y = 0; y < alto; y++) {
    final fila = y * ancho * 4;
    for (var x = 0; x < ancho; x++) {
      if (rgba[fila + x * 4 + 3] > 20) {
        if (x < izquierda) izquierda = x;
        if (x > derecha) derecha = x;
        if (y < arriba) arriba = y;
        if (y > abajo) abajo = y;
      }
    }
  }
  if (derecha < 0) return null;
  return [izquierda, arriba, derecha, abajo];
}


/// Dibuja la prenda deformada sobre el cuerpo. [area] es el rectángulo
/// donde se ve la imagen de la cámara (en pantalla o en la foto) y
/// [recorte] la parte del PNG donde está la prenda (null = imagen completa).
void dibujarPrenda(
  Canvas canvas,
  PoseFrame frame,
  ui.Image imagen,
  Rect? recorte,
  Rect area,
  double factor,
) {
  final vertices = _MallaPrenda.construir(
    frame: frame,
    recorte: recorte ??
        Rect.fromLTWH(0, 0, imagen.width.toDouble(), imagen.height.toDouble()),
    area: area,
    factor: factor,
  );
  if (vertices == null) return;

  final identidad = Float64List.fromList([
    1, 0, 0, 0,
    0, 1, 0, 0,
    0, 0, 1, 0,
    0, 0, 0, 1,
  ]);
  final paint = Paint()
    ..shader = ImageShader(
      imagen,
      TileMode.decal,
      TileMode.decal,
      identidad,
      filterQuality: FilterQuality.medium,
    );
  canvas.drawVertices(vertices, BlendMode.srcOver, paint);
}


/// Malla que deforma la imagen de la prenda según el cuerpo.
///
/// Supone la foto de una prenda de frente, estirada (como una polera
/// sobre una mesa): el torso ocupa el centro de la imagen y las mangas
/// los costados. Las proporciones de abajo se miden sobre el recorte sin
/// bordes transparentes; AJUSTAR ACÁ si la prenda queda muy ancha, larga o
/// alta.
class _MallaPrenda {
  // Columnas (proporción del ancho de la imagen) donde empieza y termina
  // el torso; lo de afuera son las mangas.
  static const double _torsoIzq = 0.25;
  static const double _torsoDer = 0.75;
  // Altura (proporción del alto de la imagen) de la línea de hombros.
  static const double _lineaHombros = 0.10;
  // Ancho del torso respecto a la distancia entre hombros.
  static const double _anchoTorso = 1.25;
  // Largo de la prenda respecto a la distancia hombros -> cadera.
  static const double _largoTorso = 1.10;
  // Giro máximo de las mangas (radianes, ~80°).
  static const double _giroMaximo = 1.4;

  static const List<double> _filas = [0.0, 0.10, 0.225, 0.45, 0.725, 1.0];
  static const List<double> _columnasTorso = [_torsoIzq, 0.5, _torsoDer];
  static const List<double> _columnasMangaIzq = [0.0, 0.125, _torsoIzq];
  static const List<double> _columnasMangaDer = [_torsoDer, 0.875, 1.0];

  static ui.Vertices? construir({
    required PoseFrame frame,
    required Rect recorte,
    required Rect area,
    required double factor,
  }) {
    Offset? enArea(Offset? n) =>
        n == null ? null : Offset(area.left + n.dx * area.width, area.top + n.dy * area.height);

    // Lado izquierdo y derecho según cómo se ven en pantalla.
    var hombroA = enArea(frame.hombroIzquierdo)!;
    var hombroB = enArea(frame.hombroDerecho)!;
    var codoA = enArea(frame.codoIzquierdo);
    var codoB = enArea(frame.codoDerecho);
    var caderaA = enArea(frame.caderaIzquierda);
    var caderaB = enArea(frame.caderaDerecha);
    if (hombroA.dx > hombroB.dx) {
      final h = hombroA;
      hombroA = hombroB;
      hombroB = h;
      final c = codoA;
      codoA = codoB;
      codoB = c;
      final k = caderaA;
      caderaA = caderaB;
      caderaB = k;
    }

    final anchoHombros = (hombroB - hombroA).distance;
    if (anchoHombros < 4) return null;

    // Ejes del torso: "a" a lo ancho, "abajo" hacia la cadera.
    final a = (hombroB - hombroA) / anchoHombros;
    var abajo = Offset(-a.dy, a.dx);
    if (abajo.dy < 0) abajo = -abajo;
    final centroHombros = (hombroA + hombroB) / 2;

    Offset centroCadera;
    var aCadera = a;
    if (caderaA != null && caderaB != null) {
      centroCadera = (caderaA + caderaB) / 2;
      final v = caderaB - caderaA;
      if (v.distance > 1) {
        aCadera = v / v.distance;
        if (aCadera.dx * a.dx + aCadera.dy * a.dy < 0) aCadera = -aCadera;
      }
    } else {
      // Sin cadera visible: largo típico respecto al ancho de hombros.
      centroCadera = centroHombros + abajo * (anchoHombros * 1.5);
    }

    var direccionTorso = centroCadera - centroHombros;
    final distanciaTorso = direccionTorso.distance;
    direccionTorso = distanciaTorso < 1 ? abajo : direccionTorso / distanciaTorso;

    final largo = math.max(distanciaTorso, anchoHombros) * _largoTorso * factor;
    final mitadAncho = anchoHombros * _anchoTorso * factor / 2;

    // Posición en pantalla de un punto (tx, ty) de la imagen de la prenda
    // sin girar las mangas.
    Offset base(double tx, double ty) {
      final t = (ty - _lineaHombros) / (1 - _lineaHombros);
      final centro = centroHombros + direccionTorso * (t * largo);
      var ancho = Offset.lerp(a, aCadera, t.clamp(0.0, 1.0).toDouble())!;
      final d = ancho.distance;
      ancho = d == 0 ? a : ancho / d;
      final u = (tx - 0.5) / (_torsoDer - 0.5);
      return centro + ancho * (u * mitadAncho);
    }

    // Giro de una manga: diferencia entre la dirección en reposo de la
    // manga (como está en la foto) y la dirección hombro -> codo.
    double giro(Offset pivote, Offset puntaReposo, Offset hombro, Offset? codo) {
      if (codo == null) return 0;
      final reposo = puntaReposo - pivote;
      final brazo = codo - hombro;
      if (reposo.distance < 1 || brazo.distance < 1) return 0;
      var delta = brazo.direction - reposo.direction;
      while (delta > math.pi) {
        delta -= 2 * math.pi;
      }
      while (delta < -math.pi) {
        delta += 2 * math.pi;
      }
      return delta.clamp(-_giroMaximo, _giroMaximo).toDouble();
    }

    Offset rotar(Offset p, Offset pivote, double angulo) {
      final v = p - pivote;
      final c = math.cos(angulo);
      final s = math.sin(angulo);
      return pivote + Offset(v.dx * c - v.dy * s, v.dx * s + v.dy * c);
    }

    final posiciones = <Offset>[];
    final texturas = <Offset>[];

    // Agrega una cuadrícula (2 triángulos por celda). [posicion] decide
    // dónde va cada vértice de la cuadrícula.
    void cuadricula(List<double> columnas, Offset Function(double tx, double ty) posicion) {
      for (var f = 0; f < _filas.length - 1; f++) {
        for (var c = 0; c < columnas.length - 1; c++) {
          final x0 = columnas[c];
          final x1 = columnas[c + 1];
          final y0 = _filas[f];
          final y1 = _filas[f + 1];
          final esquinas = [
            [x0, y0], [x1, y0], [x1, y1],
            [x0, y0], [x1, y1], [x0, y1],
          ];
          for (final e in esquinas) {
            posiciones.add(posicion(e[0], e[1]));
            texturas.add(Offset(
              recorte.left + e[0] * recorte.width,
              recorte.top + e[1] * recorte.height,
            ));
          }
        }
      }
    }

    // Torso.
    cuadricula(_columnasTorso, base);

    // Manga izquierda (en pantalla): el borde pegado al torso no se mueve,
    // el borde de afuera gira por completo y el del medio a la mitad.
    final pivoteA = base(_torsoIzq, _lineaHombros + 0.03);
    final giroA = giro(pivoteA, base(0.0, 0.225), hombroA, codoA);
    cuadricula(_columnasMangaIzq, (tx, ty) {
      final peso = (_torsoIzq - tx) / _torsoIzq;
      return rotar(base(tx, ty), pivoteA, giroA * peso);
    });

    // Manga derecha (en pantalla).
    final pivoteB = base(_torsoDer, _lineaHombros + 0.03);
    final giroB = giro(pivoteB, base(1.0, 0.225), hombroB, codoB);
    cuadricula(_columnasMangaDer, (tx, ty) {
      final peso = (tx - _torsoDer) / (1 - _torsoDer);
      return rotar(base(tx, ty), pivoteB, giroB * peso);
    });

    return ui.Vertices(
      ui.VertexMode.triangles,
      posiciones,
      textureCoordinates: texturas,
    );
  }
}