from machine import Pin, PWM, unique_id
import ubinascii
import time
import network
import ntptime
import urequests
import ujson
from umqtt.simple import MQTTClient

# ============================================================
# POMOPET - NODO COFRE
# ESP32 + Microswitch + Servomotor + MQTT + Supabase
# Thonny / MicroPython
# ============================================================

# -----------------------------
# CONFIGURACION DEMO
# -----------------------------

# Para demo rápida:
# - TIEMPO_ESPERA = segundos antes de bloquear el cofre
# - MODO_MINUTOS = lo que verá la página como duración de sesión
TIEMPO_ESPERA = 3
MODO_MINUTOS = 1

# -----------------------------
# IDENTIFICADORES
# -----------------------------

POMO_MQTT_ID = "POMO001"

USUARIO_ID_SUPABASE = "ef372402-b41e-45b0-ad06-119a23ed42ec"

DEVICE_ID = "cofre-" + ubinascii.hexlify(unique_id()).decode()

# -----------------------------
# WIFI
# -----------------------------

WIFI_SSID = "su_wifi_2.4"
WIFI_PASS = "contraseña"

# -----------------------------
# MQTT
# -----------------------------

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

TOPIC_COFRE_STATUS = ("pomopet/" + POMO_MQTT_ID + "/cofre/status").encode()
TOPIC_COFRE_COMANDO = ("pomopet/" + POMO_MQTT_ID + "/cofre/comando").encode()

mqtt_client = None

# -----------------------------
# SUPABASE
# -----------------------------

SUPABASE_URL = "https://hiyceghgbunqektkswcg.supabase.co"

# PEGA AQUÍ LA SECRET/SERVICE KEY, NO la publishable/anon.
# NO la subas a GitHub.
SUPABASE_KEY = "la_clave_secreta"

SUPABASE_ESTADO_URL = (
    SUPABASE_URL
    + "/rest/v1/estado_dispositivo?usuario_id=eq."
    + USUARIO_ID_SUPABASE
)

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# -----------------------------
# PINES
# -----------------------------

MICROSWITCH_PIN = 14
SERVO_PIN = 18

# Microswitch con PULL_UP:
# libre = 1
# presionado = 0
microswitch = Pin(MICROSWITCH_PIN, Pin.IN, Pin.PULL_UP)

servo = PWM(Pin(SERVO_PIN), freq=50)

# -----------------------------
# SERVO / COFRE
# -----------------------------

ANGULO_ABIERTO = 20
ANGULO_CERRADO = 120

bloqueado = False
wifi_ok = False
esperando_retiro = False


# ============================================================
# UTILIDADES
# ============================================================

def iso_utc_now():
    try:
        t = time.localtime()
        return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
            t[0], t[1], t[2], t[3], t[4], t[5]
        )
    except:
        return None


def sincronizar_hora():
    try:
        print("Sincronizando hora NTP...")
        ntptime.settime()
        print("Hora NTP OK:", iso_utc_now())
    except Exception as e:
        print("No se pudo sincronizar NTP:", e)


# ============================================================
# WIFI / MQTT
# ============================================================
def sub_cb(topic, msg):
    global esperando_retiro

    print("MQTT recibido:", topic, msg)

    if topic == TOPIC_COFRE_COMANDO:
        if msg == b"abrir":
            print("Comando recibido: abrir cofre")

            if bloqueado:
                abrir_cofre("sesion completa")
                esperando_retiro = True
            else:
                print("El cofre ya estaba abierto.")
                
def conectar_redes():
    global mqtt_client, wifi_ok

    print("Conectando a WiFi...", end="")

    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    if not sta.isconnected():
        sta.connect(WIFI_SSID, WIFI_PASS)

        inicio = time.time()

        while not sta.isconnected():
            time.sleep(0.5)
            print(".", end="")

            if time.time() - inicio > 20:
                print("\nNo se pudo conectar a WiFi.")
                print("Revisa SSID, clave y que sea red 2.4 GHz.")
                wifi_ok = False
                return False

    wifi_ok = True

    print("\nWiFi OK! IP:", sta.ifconfig()[0])

    sincronizar_hora()

    try:
        print("Conectando a MQTT...")
        mqtt_client = MQTTClient(DEVICE_ID, MQTT_BROKER, port=MQTT_PORT)
        mqtt_client.set_callback(sub_cb)
        mqtt_client.connect()
        mqtt_client.subscribe(TOPIC_COFRE_COMANDO)

        print("MQTT conectado!")
        print("Suscrito a comando:", TOPIC_COFRE_COMANDO)
    except Exception as e:
        print("Error conectando a MQTT:", e)
        mqtt_client = None

    return True


def publicar_mqtt(mensaje):
    global mqtt_client

    print("Publicando MQTT:", mensaje)

    if mqtt_client is None:
        print("MQTT no disponible.")
        return

    try:
        mqtt_client.publish(TOPIC_COFRE_STATUS, mensaje)
    except Exception as e:
        print("ERROR MQTT:", e)


# ============================================================
# SUPABASE
# ============================================================

def actualizar_supabase(celular_dentro, servo_bloqueado, estado_sesion):
    if not wifi_ok:
        print("Sin WiFi: no se actualiza Supabase.")
        return

    payload = {
        "celular_dentro": celular_dentro,
        "servo_bloqueado": servo_bloqueado,
        "estado_sesion": estado_sesion,
        "modo_minutos": MODO_MINUTOS,
        "segundos_restantes": MODO_MINUTOS * 60 if estado_sesion == 1 else 0
    }

    ahora = iso_utc_now()
    if ahora is not None:
        payload["ultima_actualizacion"] = ahora

    print("Enviando a Supabase:", payload)

    try:
        r = urequests.request(
            "PATCH",
            SUPABASE_ESTADO_URL,
            data=ujson.dumps(payload),
            headers=SUPABASE_HEADERS
        )

        print("Supabase status:", r.status_code)

        try:
            print("Supabase respuesta:", r.text)
        except:
            pass

        r.close()

    except Exception as e:
        print("ERROR HTTP Supabase:", e)


# ============================================================
# HARDWARE
# ============================================================

def mover_servo(angulo):
    duty = int(25 + (angulo * 100 / 180))
    servo.duty(duty)
    print("Servo a", angulo, "grados")
    time.sleep(0.4)


def celular_detectado():
    return microswitch.value() == 0


def abrir_cofre(motivo):
    global bloqueado

    mover_servo(ANGULO_ABIERTO)
    bloqueado = False

    print("COFRE ABIERTO:", motivo)

    publicar_mqtt(b"abierto")

    # Estados:
    # 0 = IDLE
    # 1 = FOCUS
    # 2 = DESCANSO / COMPLETADA
    # 3 = ALERTA / INTERRUPCION

    if "completa" in motivo:
        actualizar_supabase(celular_detectado(), False, 2)

    elif "interrup" in motivo or "retirado" in motivo:
        actualizar_supabase(False, False, 3)

    else:
        actualizar_supabase(False, False, 0)


def cerrar_cofre():
    global bloqueado

    mover_servo(ANGULO_CERRADO)
    bloqueado = True

    print("COFRE BLOQUEADO")

    publicar_mqtt(b"bloqueado")
    actualizar_supabase(True, True, 1)


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

print("POMO_MQTT_ID:", POMO_MQTT_ID)
print("USUARIO_ID_SUPABASE:", USUARIO_ID_SUPABASE)
print("DEVICE_ID:", DEVICE_ID)
print("TOPIC MQTT:", TOPIC_COFRE_STATUS)

conectar_redes()

abrir_cofre("inicio")

print("Esperando celular...")

while True:

    # 1) Escuchar comandos MQTT del Tamagotchi
    # Ej: b"abrir" en pomopet/POMO001/cofre/comando
    if mqtt_client is not None:
        try:
            mqtt_client.check_msg()
        except Exception as e:
            print("Error leyendo MQTT:", e)

    # 2) Si la sesión terminó y el cofre se abrió,
    # esperar a que el usuario retire el celular antes de volver a bloquear.
    if esperando_retiro:
        if not celular_detectado():
            print("Celular retirado después de sesión completa. Cofre listo.")
            esperando_retiro = False
            actualizar_supabase(False, False, 0)

        time.sleep(0.2)
        continue

    # 3) Si detecta celular y el cofre está abierto, inicia bloqueo
    if celular_detectado() and not bloqueado:
        print("Celular detectado")

        cancelado = False

        for i in range(TIEMPO_ESPERA, 0, -1):
            print("Bloqueando en", i)
            time.sleep(1)

            if not celular_detectado():
                print("Se dejó de sentir presión antes de bloquear")
                abrir_cofre("bloqueo cancelado")
                cancelado = True
                break

        if not cancelado and celular_detectado():
            cerrar_cofre()

    # 4) Si estaba bloqueado y se pierde presión, es interrupción
    if bloqueado and not celular_detectado():
        print("Se perdió presión con el cofre bloqueado")
        abrir_cofre("celular retirado / interrupcion")

    time.sleep(0.2)