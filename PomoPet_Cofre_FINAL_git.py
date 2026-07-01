from machine import Pin, PWM, unique_id
import ubinascii
import time
import network
import ntptime
import urequests
import ujson
import gc
from umqtt.simple import MQTTClient

# ============================================================
# POMOPET COFRE - FINAL SEGURO
# Prioridad: NO ATRAPAR CELULAR + MQTT ESTABLE + Supabase liviano
# ============================================================

# -----------------------------
# CONFIGURACION
# -----------------------------
TIEMPO_ESPERA = 5
MODO_MINUTOS = 1

POMO_MQTT_ID = "POMO001"
USUARIO_ID_SUPABASE = "ef372402-b41e-45b0-ad06-119a23ed42ec"
DEVICE_ID = "cofre-" + ubinascii.hexlify(unique_id()).decode()

WIFI_SSID = "Tu-Wifi"
WIFI_PASS = "Tu-contraseña"

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
MQTT_REINTENTO_MS = 5000
MQTT_PING_MS = 25000

TOPIC_COFRE_STATUS = ("pomopet/" + POMO_MQTT_ID + "/cofre/status").encode()
TOPIC_COFRE_COMANDO = ("pomopet/" + POMO_MQTT_ID + "/cofre/comando").encode()
TOPIC_VIDA = ("pomopet/" + POMO_MQTT_ID + "/mascota/vida").encode()

# Supabase: mantener liviano. No pedir JSON gigante al ESP32.
SUPABASE_URL = "https://hiyceghgbunqektkswcg.supabase.co"
SUPABASE_KEY = "sb_secret_key de supabase"
SUPABASE_ESTADO_URL = SUPABASE_URL + "/rest/v1/estado_dispositivo?usuario_id=eq." + USUARIO_ID_SUPABASE
SUPABASE_SESIONES_URL = SUPABASE_URL + "/rest/v1/sesiones"
SUPABASE_HISTORIAL_URL = SUPABASE_URL + "/rest/v1/historial_sesiones"
SUPABASE_MASCOTAS_URL = SUPABASE_URL + "/rest/v1/mascotas?usuario_id=eq." + USUARIO_ID_SUPABASE

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
    "Connection": "close"
}

# Pines
MICROSWITCH_PIN = 14
SERVO_PIN = 18
microswitch = Pin(MICROSWITCH_PIN, Pin.IN, Pin.PULL_UP)
servo = PWM(Pin(SERVO_PIN), freq=50)

ANGULO_ABIERTO = 20
ANGULO_CERRADO = 120

# Estados internos
bloqueado = False
bloqueo_pausado = False
esperando_retiro = False
sesion_autorizada = False      # CLAVE: solo el arcade puede autorizar bloqueo
sesion_actual_id = None
sesion_inicio_epoch = None
vida_arcade = 5

mqtt_client = None
mqtt_ok = False
wifi_ok = False
ultimo_intento_mqtt = 0
ultimo_ping_mqtt = 0
ultimo_estado_mqtt_ms = 0

# ============================================================
# UTILIDADES
# ============================================================
def ticks_ms():
    return time.ticks_ms()


def iso_utc_now():
    try:
        t = time.localtime()
        return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(t[0], t[1], t[2], t[3], t[4], t[5])
    except:
        return None


def hora_actual_utc():
    ahora = iso_utc_now()
    if ahora:
        return ahora[11:19]
    return "00:00:00"


def uuid_local():
    # UUID pseudoaleatorio suficiente para demo/local.
    base = ubinascii.hexlify(unique_id()).decode() + "%08x" % (time.ticks_ms() & 0xffffffff) + "%08x" % (time.time() & 0xffffffff)
    h = (base + "0" * 32)[:32]
    return h[0:8] + "-" + h[8:12] + "-4" + h[13:16] + "-a" + h[17:20] + "-" + h[20:32]


def modo_minutos_sesion():
    # Tu tabla sesiones acepta 25, 45 o 60. En demo se muestra 1 min, pero se guarda 25.
    if MODO_MINUTOS in (25, 45, 60):
        return MODO_MINUTOS
    return 25

# ============================================================
# HARDWARE
# ============================================================
def mover_servo(angulo):
    duty = int(25 + (angulo * 100 / 180))
    servo.duty(duty)
    print("Servo a", angulo, "grados")
    time.sleep(0.4)


def celular_detectado():
    # PULL_UP: presionado = 0 = celular dentro. Debounce simple.
    presion = 0
    for _ in range(5):
        if microswitch.value() == 0:
            presion += 1
        time.sleep_ms(8)
    return presion >= 3


def estado_sesion_actual():
    if bloqueado:
        return 1
    if bloqueo_pausado or esperando_retiro:
        return 2
    return 0

# ============================================================
# RED / MQTT
# ============================================================
def wifi_conectar(reiniciar=False):
    global wifi_ok
    gc.collect()
    sta = network.WLAN(network.STA_IF)
    try:
        if reiniciar:
            sta.disconnect()
            sta.active(False)
            time.sleep(1)
    except:
        pass

    try:
        sta.active(True)
    except Exception as e:
        print("No se pudo activar WiFi:", e)
        wifi_ok = False
        return False

    if sta.isconnected():
        wifi_ok = True
        return True

    print("Conectando WiFi...", end="")
    try:
        sta.connect(WIFI_SSID, WIFI_PASS)
    except Exception as e:
        print("\nError WiFi:", e)
        wifi_ok = False
        return False

    inicio = time.time()
    while not sta.isconnected():
        print(".", end="")
        time.sleep(0.5)
        if time.time() - inicio > 20:
            print("\nWiFi timeout")
            wifi_ok = False
            return False

    wifi_ok = True
    print("\nWiFi OK! IP:", sta.ifconfig()[0])
    try:
        ntptime.settime()
        print("Hora NTP OK:", iso_utc_now())
    except Exception as e:
        print("NTP no disponible:", e)
    return True


def mqtt_marcar_desconectado(e=None):
    global mqtt_client, mqtt_ok
    if e:
        print("MQTT desconectado:", e)
    try:
        if mqtt_client:
            mqtt_client.disconnect()
    except:
        pass
    mqtt_client = None
    mqtt_ok = False
    gc.collect()


def publicar_mqtt(msg):
    global mqtt_client, mqtt_ok
    print("Publicando MQTT:", msg)
    if not mqtt_asegurar_conexion():
        print("MQTT no disponible.")
        return False
    try:
        mqtt_client.publish(TOPIC_COFRE_STATUS, msg)
        return True
    except Exception as e:
        mqtt_marcar_desconectado(e)
        return False


def conectar_redes(reiniciar_wifi=False):
    global mqtt_client, mqtt_ok, ultimo_intento_mqtt, ultimo_ping_mqtt
    ultimo_intento_mqtt = ticks_ms()
    if not wifi_conectar(reiniciar_wifi):
        mqtt_ok = False
        return False
    try:
        gc.collect()
        mqtt_client = MQTTClient(DEVICE_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        mqtt_client.set_callback(sub_cb)
        mqtt_client.connect(clean_session=True)
        mqtt_client.subscribe(TOPIC_COFRE_COMANDO)
        mqtt_client.subscribe(TOPIC_VIDA)
        mqtt_ok = True
        ultimo_ping_mqtt = ticks_ms()
        print("MQTT conectado!")
        print("Suscrito a:", TOPIC_COFRE_COMANDO, TOPIC_VIDA)
        publicar_mqtt(b"online")
        return True
    except Exception as e:
        print("Error conectando MQTT:", e)
        mqtt_marcar_desconectado()
        return False


def mqtt_asegurar_conexion():
    global ultimo_intento_mqtt
    if mqtt_client is not None and mqtt_ok:
        return True
    ahora = ticks_ms()
    if time.ticks_diff(ahora, ultimo_intento_mqtt) >= MQTT_REINTENTO_MS:
        return conectar_redes(False)
    return False


def mqtt_loop():
    global ultimo_ping_mqtt
    if not mqtt_asegurar_conexion():
        return
    try:
        mqtt_client.check_msg()
        ahora = ticks_ms()
        if time.ticks_diff(ahora, ultimo_ping_mqtt) >= MQTT_PING_MS:
            mqtt_client.ping()
            ultimo_ping_mqtt = ahora
    except Exception as e:
        mqtt_marcar_desconectado(e)

# ============================================================
# SUPABASE LIVIANO
# ============================================================
def supabase_request(method, url, payload=None):
    if not wifi_ok:
        return None
    try:
        gc.collect()
        data = None if payload is None else ujson.dumps(payload)
        r = urequests.request(method, url, data=data, headers=SUPABASE_HEADERS)
        status = r.status_code
        try:
            r.close()
        except:
            pass
        gc.collect()
        print("Supabase", method, "status:", status)
        return status
    except Exception as e:
        print("ERROR HTTP Supabase:", e)
        gc.collect()
        return None


def actualizar_estado(celular_dentro=None, servo_bloqueado=None, estado_sesion=None):
    if celular_dentro is None:
        celular_dentro = celular_detectado()
    if servo_bloqueado is None:
        servo_bloqueado = bloqueado
    if estado_sesion is None:
        estado_sesion = estado_sesion_actual()
    ahora = iso_utc_now()
    payload = {
        "celular_dentro": celular_dentro,
        "servo_bloqueado": servo_bloqueado,
        "estado_sesion": estado_sesion,
        "modo_minutos": MODO_MINUTOS,
        "segundos_restantes": MODO_MINUTOS * 60 if estado_sesion == 1 else 0,
        "corazones": vida_arcade
    }
    if ahora:
        payload["ultima_actualizacion"] = ahora
        payload["actualizado_en"] = ahora
    print("Actualizando estado_dispositivo:", payload)
    return supabase_request("PATCH", SUPABASE_ESTADO_URL, payload)




def actualizar_mascota_corazones():
    # La web del panel lateral lee los corazones desde mascotas.corazones,
    # no desde estado_dispositivo.corazones. Actualizamos SOLO corazones/humor
    # para no seguir subiendo XP o nivel durante las pruebas.
    humor = "triste" if vida_arcade <= 0 else ("neutral" if vida_arcade <= 2 else "feliz")
    payload = {
        "corazones": vida_arcade,
        "sprite_humor": humor
    }
    ahora = iso_utc_now()
    if ahora:
        payload["actualizado_en"] = ahora
    print("Actualizando mascotas.corazones:", payload)
    return supabase_request("PATCH", SUPABASE_MASCOTAS_URL, payload)

def crear_sesion():
    global sesion_actual_id, sesion_inicio_epoch
    sesion_actual_id = uuid_local()
    sesion_inicio_epoch = time.time()
    ahora = iso_utc_now()
    payload = {
        "id": sesion_actual_id,
        "usuario_id": USUARIO_ID_SUPABASE,
        "modo_minutos": modo_minutos_sesion(),
        "tipo": "focus",
        "estado": "en_curso",
        "celular_dentro": True,
        "interrupciones": 0,
        "xp_ganado": 0
    }
    if ahora:
        payload["iniciada_en"] = ahora
    print("Creando sesion:", payload)
    supabase_request("POST", SUPABASE_SESIONES_URL, payload)


def finalizar_sesion(estado_final):
    global sesion_actual_id, sesion_inicio_epoch
    if sesion_actual_id is None:
        return
    ahora = iso_utc_now()
    payload = {
        "estado": estado_final,
        "celular_dentro": celular_detectado(),
        "interrupciones": 1 if estado_final == "interrumpida" else 0,
        "xp_ganado": 10 if estado_final == "completada" else 0
    }
    if ahora:
        payload["finalizada_en"] = ahora
    supabase_request("PATCH", SUPABASE_SESIONES_URL + "?id=eq." + sesion_actual_id, payload)

    # Historial visible en dashboard; si falla, no rompe la demo.
    hist = {
        "sesion_id": sesion_actual_id,
        "usuario_id": USUARIO_ID_SUPABASE,
        "titulo": "Pomodoro completado" if estado_final == "completada" else "Pomodoro interrumpido",
        "hora_inicio": hora_actual_utc(),
        "duracion_str": str(MODO_MINUTOS) + " min",
        "tipo_resultado": "ok" if estado_final == "completada" else "fail"
    }
    supabase_request("POST", SUPABASE_HISTORIAL_URL, hist)
    sesion_actual_id = None
    sesion_inicio_epoch = None

# ============================================================
# COMANDOS MQTT
# ============================================================
def sub_cb(topic, msg):
    global MODO_MINUTOS, bloqueo_pausado, esperando_retiro, sesion_autorizada, bloqueado, vida_arcade
    print("MQTT recibido:", topic, msg)

    if topic == TOPIC_VIDA:
        try:
            vida_arcade = max(0, min(5, int(msg)))
            print("Vida arcade:", vida_arcade)
            actualizar_mascota_corazones()
            # Tambien sincroniza estado_dispositivo.corazones para que ambas tablas coincidan.
            actualizar_estado(celular_detectado(), bloqueado, estado_sesion_actual())
        except Exception as e:
            print("No se pudo actualizar vida:", e)
        return

    if topic != TOPIC_COFRE_COMANDO:
        return

    if msg.startswith(b"modo:"):
        try:
            MODO_MINUTOS = int(msg.split(b":")[1])
            sesion_autorizada = True
            print("Sesion autorizada desde arcade. Modo:", MODO_MINUTOS)
            actualizar_estado(celular_detectado(), bloqueado, 1 if bloqueado else 0)
        except Exception as e:
            print("Error modo:", e)
        return

    if msg in (b"abrir", b"abrir_descanso", b"descanso"):
        print("Abrir para descanso / sesion completa")
        bloqueo_pausado = True
        esperando_retiro = True
        if bloqueado:
            abrir_cofre("sesion completa / descanso")
        else:
            mover_servo(ANGULO_ABIERTO)
            bloqueado = False
            publicar_mqtt(b"abierto")
            actualizar_estado(celular_detectado(), False, 2)
        return

    if msg == b"fin_descanso":
        print("Fin descanso")
        esperando_retiro = False
        bloqueo_pausado = False
        # Sigue siendo sesion autorizada, porque queda otro pomodoro.
        sesion_autorizada = True
        if celular_detectado():
            publicar_mqtt(b"celular_presente")
            cerrar_cofre()
        else:
            publicar_mqtt(b"celular_ausente")
            actualizar_estado(False, False, 0)
        return

    if msg == b"cancelar":
        print("Cancelar / abrir seguro")
        sesion_autorizada = False
        bloqueo_pausado = False
        esperando_retiro = False
        if bloqueado:
            abrir_cofre("interrupcion por arcade")
        else:
            mover_servo(ANGULO_ABIERTO)
            bloqueado = False
            publicar_mqtt(b"abierto")
            actualizar_estado(celular_detectado(), False, 3)
        return

# ============================================================
# ACCIONES COFRE
# ============================================================
def abrir_cofre(motivo):
    global bloqueado, sesion_autorizada
    mover_servo(ANGULO_ABIERTO)
    bloqueado = False
    print("COFRE ABIERTO:", motivo)

    if "interrup" in motivo or "retirado" in motivo:
        publicar_mqtt(b"interrumpido")
        finalizar_sesion("interrumpida")
        sesion_autorizada = False
        actualizar_estado(False, False, 3)
    elif "completa" in motivo:
        publicar_mqtt(b"abierto")
        finalizar_sesion("completada")
        actualizar_estado(celular_detectado(), False, 2)
    else:
        publicar_mqtt(b"abierto")
        actualizar_estado(celular_detectado(), False, 0)


def cerrar_cofre():
    global bloqueado
    if not sesion_autorizada:
        print("Bloqueo ignorado: NO hay sesion autorizada por arcade.")
        mover_servo(ANGULO_ABIERTO)
        bloqueado = False
        publicar_mqtt(b"abierto")
        actualizar_estado(celular_detectado(), False, 0)
        return

    mover_servo(ANGULO_CERRADO)
    bloqueado = True
    print("COFRE BLOQUEADO")
    publicar_mqtt(b"bloqueado")
    actualizar_estado(True, True, 1)
    crear_sesion()

# ============================================================
# ARRANQUE
# ============================================================
print("DEVICE_ID:", DEVICE_ID)
conectar_redes(reiniciar_wifi=True)
sesion_autorizada = False
abrir_cofre("inicio")
print("Esperando comandos del arcade...")

while True:
    mqtt_loop()

    # Si hay celular dentro fuera de una sesion, NO bloquear. Solo avisar de vez en cuando.
    ahora = ticks_ms()
    if celular_detectado() and not bloqueado and not bloqueo_pausado and not sesion_autorizada:
        if time.ticks_diff(ahora, ultimo_estado_mqtt_ms) > 2500:
            ultimo_estado_mqtt_ms = ahora
            print("Celular dentro, pero sin sesion activa: se mantiene abierto.")
            publicar_mqtt(b"celular_presente")
            actualizar_estado(True, False, 0)
        time.sleep(0.2)
        continue

    # Si el arcade autorizo sesion y detecta celular, ahi si bloquea.
    if celular_detectado() and not bloqueado and not bloqueo_pausado and sesion_autorizada:
        print("Celular detectado para sesion activa")
        publicar_mqtt(b"celular_presente")
        actualizar_estado(True, False, 0)
        cancelado = False
        for i in range(TIEMPO_ESPERA, 0, -1):
            print("Bloqueando en", i)
            time.sleep(1)
            mqtt_loop()
            if not celular_detectado():
                print("Se dejó de detectar celular antes de bloquear")
                abrir_cofre("bloqueo cancelado")
                cancelado = True
                break
        if not cancelado and celular_detectado():
            cerrar_cofre()

    # Interrupcion fisica durante focus.
    if bloqueado and not celular_detectado():
        print("Se perdió presión con cofre bloqueado")
        abrir_cofre("celular retirado / interrupcion")

    # Durante descanso, mantener abierto hasta fin_descanso.
    # IMPORTANTE: si el usuario saca el celular durante descanso, tambien
    # actualizamos Supabase a celular_dentro=False. Antes solo se publicaba MQTT,
    # por eso la pagina se quedaba pegada diciendo SI.
    if esperando_retiro:
        if not celular_detectado():
            if time.ticks_diff(ahora, ultimo_estado_mqtt_ms) > 1200:
                ultimo_estado_mqtt_ms = ahora
                publicar_mqtt(b"celular_ausente")
                actualizar_estado(False, False, 2 if bloqueo_pausado else 0)
        if bloqueo_pausado:
            time.sleep(0.2)
            continue

    time.sleep(0.2)
