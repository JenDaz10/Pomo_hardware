from machine import Pin, PWM, unique_id
import ubinascii
import time
import network
from umqtt.simple import MQTTClient

# ============================================================
# POMOPET - NODO COFRE
# ESP32 + Microswitch + Servomotor + MQTT
# Thonny / MicroPython
# ============================================================

# -----------------------------
# IDENTIFICADORES
# -----------------------------

POMO_ID = "POMO001"
DEVICE_ID = "cofre-" + ubinascii.hexlify(unique_id()).decode()

# -----------------------------
# WIFI / MQTT
# -----------------------------

WIFI_SSID = "MENDEZ-2.4G"
WIFI_PASS = "ElCarmen9800"

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

TOPIC_COFRE_STATUS = b"pomopet/POMO001/cofre/status"

mqtt_client = None

# -----------------------------
# PINES
# -----------------------------

MICROSWITCH_PIN = 14
SERVO_PIN = 18

microswitch = Pin(MICROSWITCH_PIN, Pin.IN, Pin.PULL_UP)
servo = PWM(Pin(SERVO_PIN), freq=50)

# -----------------------------
# CONFIGURACION DEL COFRE
# -----------------------------

ANGULO_ABIERTO = 20
ANGULO_CERRADO = 120
TIEMPO_ESPERA = 10

bloqueado = False


# ============================================================
# MQTT / WIFI
# ============================================================

def conectar_redes():
    global mqtt_client

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
                return False

    print("\nWiFi OK! IP:", sta.ifconfig()[0])

    try:
        print("Conectando a MQTT...")
        mqtt_client = MQTTClient(DEVICE_ID, MQTT_BROKER, port=MQTT_PORT)
        mqtt_client.connect()
        print("¡MQTT Conectado!")
        return True

    except Exception as e:
        print("Error conectando a MQTT:", e)
        return False


def publicar_estado(mensaje):
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
# HARDWARE
# ============================================================

def mover_servo(angulo):
    duty = int(25 + (angulo * 100 / 180))
    servo.duty(duty)
    time.sleep(0.4)


def celular_detectado():
    # Con PULL_UP:
    # libre = 1
    # presionado = 0
    return microswitch.value() == 0


def abrir_cofre(motivo):
    global bloqueado

    mover_servo(ANGULO_ABIERTO)
    bloqueado = False

    print("COFRE ABIERTO:", motivo)
    publicar_estado(b"abierto")


def cerrar_cofre():
    global bloqueado

    mover_servo(ANGULO_CERRADO)
    bloqueado = True

    print("COFRE BLOQUEADO")
    publicar_estado(b"bloqueado")


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

print("POMO_ID:", POMO_ID)
print("DEVICE_ID:", DEVICE_ID)
print("TOPIC:", TOPIC_COFRE_STATUS)

conectar_redes()

abrir_cofre("inicio")

print("Esperando celular...")

while True:

    if celular_detectado() and not bloqueado:
        print("Celular detectado")

        cancelado = False

        for i in range(TIEMPO_ESPERA, 0, -1):
            print("Bloqueando en", i)
            time.sleep(1)

            if not celular_detectado():
                print("Se dejó de sentir presión")
                abrir_cofre("bloqueo cancelado")
                cancelado = True
                break

        if not cancelado and celular_detectado():
            cerrar_cofre()

    if bloqueado and not celular_detectado():
        print("Se perdió presión con el cofre bloqueado")
        abrir_cofre("celular retirado / interrupción")

    time.sleep(0.2)