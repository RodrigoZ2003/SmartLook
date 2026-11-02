# backend/apps/sales/integrations/stripe_payment.py
#
# Procesamiento de pago con tarjeta para CU15, vía Stripe (modo test).
# MODIFICADO (Fase 2 - CU12): reembolso del pago al completar una devolución.
# El cliente ingresa la tarjeta en un campo real de Stripe.js en el
# navegador (ej. 4242 4242 4242 4242), no un payment_method fijo del
# backend - así queda visible el flujo de pago real en la demo.

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

TASA_USD_BOB = 6.96  # tasa fija de referencia, solo para la pasarela de prueba

class PagoRechazadoError(Exception):
    pass

def crear_intento_pago(monto_bs):
    """
    Crea un PaymentIntent SIN confirmar. Devuelve (id, client_secret):
    el client_secret se lo pasamos al frontend para que Stripe.js
    confirme el pago con la tarjeta que el cliente escriba.
    """
    monto_usd = round(float(monto_bs) / TASA_USD_BOB, 2)
    monto_centavos = int(monto_usd * 100)

    try:
        intent = stripe.PaymentIntent.create(
            amount=monto_centavos,
            currency="usd",
            automatic_payment_methods={
                "enabled": True,
                "allow_redirects": "never",
            },
        )
    except stripe.error.StripeError as e:
        raise PagoRechazadoError(str(e))

    return intent.id, intent.client_secret

def verificar_pago(payment_intent_id):
    """
    Verifica contra Stripe (server-to-server) que el PaymentIntent
    efectivamente se cobró antes de cerrar la orden.
    """
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as e:
        raise PagoRechazadoError(str(e))

    if intent.status != "succeeded":
        raise PagoRechazadoError(f"Pago no completado (estado: {intent.status})")

    return intent.id


# NUEVO (Fase 2 - CU12): reembolso (total o parcial) de un pago con tarjeta.
def reembolsar_pago(payment_intent_id, monto_bs):
    """
    Reembolsa monto_bs (convertido a USD con la misma tasa del cobro) del
    PaymentIntent. Nunca pide más de lo que queda sin reembolsar en Stripe
    (el redondeo de varias devoluciones parciales podría pasarse por un
    centavo). Devuelve el id del reembolso (re_...).
    """
    monto_usd = round(float(monto_bs) / TASA_USD_BOB, 2)
    monto_centavos = int(round(monto_usd * 100))
    if monto_centavos <= 0:
        raise PagoRechazadoError("El monto a reembolsar es cero.")

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id, expand=["latest_charge"])
        cargo = intent.latest_charge
        if intent.status != "succeeded" or not cargo:
            raise PagoRechazadoError("El pago no está cobrado; no se puede reembolsar.")
        disponible = cargo.amount - cargo.amount_refunded
        if disponible <= 0:
            raise PagoRechazadoError("El pago ya se reembolsó por completo.")
        reembolso = stripe.Refund.create(
            payment_intent=payment_intent_id,
            amount=min(monto_centavos, disponible),
        )
    except stripe.error.StripeError as e:
        raise PagoRechazadoError(str(e))

    return reembolso.id