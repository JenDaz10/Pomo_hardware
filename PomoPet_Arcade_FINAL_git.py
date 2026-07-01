# VERSION FIX: REINTENTO ESPERANDO COFRE + DOS MODOS SIN QUITAR FUNCIONES
# ============================================================
# POMOPET ARCADE - DEMO COMPLETO ESTABLE
# ESP32 + LCD 20x4 I2C + Joystick + 2 botones + Buzzer + MQTT
#
# Pomodoro clasico por TIEMPO TOTAL elegido:
# 25 min -> focus 25 + descanso 5 -> termina
# 50 min -> focus 25 + descanso 5 + focus 25 + descanso 5 -> termina
#
# Tiene dos modos de estudio:
# - Demo: 25 min se demuestran como 60 s, descanso 30 s.
# - Pomodoro: 25 min reales, descanso 5 min.
# ============================================================

from machine import Pin, I2C, ADC, PWM, unique_id
from lcd_i2c import LCD
import utime
import ubinascii
import gc

# -----------------------------
# CONFIGURACION PRINCIPAL
# -----------------------------
MODO_PRESENTACION = True     # Se cambia desde el menu: Demo o Pomodoro
POMODORO_DEMO_SEG = 60
DESCANSO_DEMO_SEG = 30
GRACIA_RETORNO_SEG = 5       # segundos para volver a poner el celular tras descanso
BACK_CANCELAR_MS = 5000      # ms manteniendo BACK presionado para interrumpir la sesion actual

# No hay que editar el codigo para cambiar modo: se elige desde el menu.
POMODORO_CLASICO_MIN = 25
DESCANSO_CORTO_MIN = 5
DESCANSO_LARGO_MIN = 15
POMODOROS_ANTES_DESCANSO_LARGO = 4

# -----------------------------
# WIFI / MQTT
# -----------------------------
MQTT_HABILITADO = True

WIFI_SSID = "tu_wifi"
WIFI_PASS = "Tu_contra"

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
MQTT_REINTENTO_MS = 5000
MQTT_PING_MS = 25000

POMO_MQTT_ID = "POMO001"
TOPIC_SUB_COFRE = b"pomopet/POMO001/cofre/status"
TOPIC_COFRE_COMANDO = b"pomopet/POMO001/cofre/comando"
TOPIC_PUB_ARCADE = b"pomopet/POMO001/arcade/estado"
TOPIC_PUB_SESION = b"pomopet/POMO001/sesion/evento"
TOPIC_PUB_VIDA = b"pomopet/POMO001/mascota/vida"

mqtt_client = None
wifi_ok = False
mqtt_ok = False
mqtt_ultimo_intento_ms = 0
mqtt_ultimo_ping_ms = 0
cofre_bloqueado = False

# Hora local para mostrar en el arcade.
# Chile continental invierno: UTC-4. Si en verano queda corrida, cambiar a -3.
UTC_OFFSET_HORAS = -4
hora_sincronizada = False

# Cargar WiFi/MQTT aqui para poder liberar memoria antes de conectar.
try:
    import network
    import ntptime
    from umqtt.simple import MQTTClient
except Exception as e:
    MQTT_HABILITADO = False
    print("MQTT deshabilitado:", e)

gc.collect()

# -----------------------------
# HARDWARE
# -----------------------------
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
lcd = LCD(39, 20, 4, i2c=i2c)
lcd.begin()

BTN_OK = Pin(14, Pin.IN, Pin.PULL_UP)
BTN_BACK = Pin(12, Pin.IN, Pin.PULL_UP)

joy_x = ADC(Pin(34))
joy_y = ADC(Pin(35))
joy_x.atten(ADC.ATTN_11DB)
joy_y.atten(ADC.ATTN_11DB)

buzzer = PWM(Pin(26))
buzzer.duty(0)

# -----------------------------
# SONIDOS
# -----------------------------
C4 = 261
D4 = 293
E4 = 329
F4 = 349
G4 = 392
A4 = 440
B4 = 494
C5 = 523
D5 = 587
E5 = 659
G5 = 784
A5 = 880

MELODIA_OK = [(C4,120),(E4,120),(G4,120),(C5,280),(0,70)]
MELODIA_TRISTE = [(G4,220),(F4,220),(E4,250),(D4,420),(0,80)]
MELODIA_ALERTA = [(A4,140),(0,70),(A4,140),(0,70),(A4,220)]
# Alerta mas notoria para interrupciones/cancelaciones.
# Tuplas de 3 valores usan duty mas alto.
MELODIA_INTERRUPCION = [(A5,140,650),(0,60,0),(A5,140,650),(0,60,0),(G5,180,650),(E5,260,600),(D4,420,450)]
MELODIA_DESCANSO_INICIO = [(E4,120),(G4,120),(C5,220),(0,80)]
MELODIA_DESCANSO_FIN = [(A5,160),(0,80),(A5,160),(0,80),(G5,260)]
MELODIA_MENU = [(D4,180),(F4,160),(A4,260),(0,160),(C5,180),(A4,220),(0,500)]

# -----------------------------
# MASCOTAS ASCII
# Sin CGRAM pesada: evita WiFi Out of Memory y mantiene mascotas.
# -----------------------------
MASCOTAS = [
    # Solo 3 mascotas para la demo: menos ruido visual y menos memoria.
    # Evitamos el backslash porque en algunos LCD HD44780 aparece como simbolo raro.
    {"nombre":"Pomo", "caras":{
        "idle":["(^-^)/"], "neutral":["(o-o)"], "wait":["(O-O)/"],
        "study":["(O-O)/"], "happy":["(^O^)/"],
        "rest":["(-u-)/"], "sad":["(;-;)/"],
        "sleep":["(-.-)z"]}},
    {"nombre":"Gato", "caras":{
        "idle":[" ^._.^ ", "(=^.^=)"], "neutral":[" ^._.^ ", "(o.o )"], "wait":[" ^._.^ ", "(O.O )"],
        "study":[" ^._.^ ", "(O-O )"], "happy":[" ^._.^ ", "(=^O^=)"],
        "rest":[" ^._.^ ", "(=u.u=)"], "sad":[" ^._.^ ", "(;-; )"],
        "sleep":[" ^._.^ ", "(-.-)z"]}},
    {"nombre":"Buho", "caras":{
        "idle":[" (o,o) ", " /|_|> "], "neutral":[" (o-o) ", " /|_|> "], "wait":[" (O,O) ", " /|_|> "],
        "study":[" (O-O) ", " /|_|> "], "happy":[" (^O^) ", " /|_|> "],
        "rest":[" (-u-) ", " /|_|> "], "sad":[" (;_;) ", " /|_|> "],
        "sleep":[" (-.-)z", " /|_|> "]}},
]

# -----------------------------
# ESTADO GLOBAL
# -----------------------------
OPCIONES = ["Demo", "Pomodoro", "Vitalidad", "Mascota", "Nombre", "Sonido", "Sistema"]
seleccion = 0
estado = "menu"

VIDA_MAX = 5
vida = VIDA_MAX
minutos_cfg = 25              # TIEMPO TOTAL de estudio elegido
minutos_restantes_total = 0   # estudio total pendiente en minutos reales
bloque_actual_min = 0
pomodoros_hechos = 0
pomodoros_totales = 1
seg_restantes = 0
verif_ultimo_ms = 0
verif_intentos = 0

necesita_dibujar = True
ultimo_tick_ms = 0
ultimo_joy_ms = 0
anim_tick_ms = 0
frame_idx = 0
musica_silenciada = False
menu_musica_idx = 0
menu_musica_ms = 0
menu_musica_sonando = False

mascota_idx = 0
mascota_preview_idx = 0
nombre_pomo = "POMO"
nombre_edit = ["P", "O", "M", "O"]
nombre_pos = 0
ALFABETO = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NAME_LEN = 4

btn_ok_prev = 1
btn_back_prev = 1
btn_back_down_ms = 0
btn_back_long_fired = False
back_hold_overlay_ms = 0
LONG_PRESS_MS = 750

# Estados donde hay una sesion en curso (foco/descanso/espera de celular).
# En estos estados BACK ya no cancela con un toque: hay que mantenerlo
# presionado BACK_CANCELAR_MS para interrumpir, asi se evita perder una
# sesion o un corazon por un toque accidental.
ESTADOS_SESION_ACTIVA = ("esperando_cofre", "focus", "descanso", "retorno_celular", "verificando_retorno")

# -----------------------------
# ARCHIVOS PEQUENOS
# -----------------------------
def cargar_archivos():
    global mascota_idx, nombre_pomo, nombre_edit, vida
    try:
        f = open("pomo_pet.txt", "r")
        v = int(f.read())
        f.close()
        if 0 <= v < len(MASCOTAS):
            mascota_idx = v
    except:
        pass

    try:
        f = open("pomo_vida.txt", "r")
        v = int(f.read())
        f.close()
        if 0 <= v <= VIDA_MAX:
            vida = v
    except:
        pass

    try:
        f = open("pomo_name.txt", "r")
        txt = f.read().strip().upper()
        f.close()
        limpio = ""
        for c in txt:
            if c in ALFABETO:
                limpio += c
        limpio = (limpio + "    ")[:NAME_LEN]
        if limpio.strip():
            nombre_pomo = limpio
            nombre_edit = list(nombre_pomo)
    except:
        pass


def guardar_mascota():
    try:
        f = open("pomo_pet.txt", "w")
        f.write(str(mascota_idx))
        f.close()
    except:
        pass


def guardar_vida():
    try:
        f = open("pomo_vida.txt", "w")
        f.write(str(vida))
        f.close()
    except:
        pass


def ajustar_vida(delta):
    """Punto UNICO donde cambia la vida (corazones).
    - La deja guardada en flash, para que sobreviva un reinicio del ESP32.
    - La publica por MQTT (TOPIC_PUB_VIDA) para que el cofre la replique
      en Supabase (mascotas.corazones) y el dashboard web quede igual
      que la pantalla del arcade.
    Nunca asignes 'vida' directamente fuera de esta funcion.
    """
    global vida
    vida = max(0, min(VIDA_MAX, vida + delta))
    guardar_vida()
    mqtt_publicar(TOPIC_PUB_VIDA, str(vida).encode())
    return vida


def guardar_nombre():
    try:
        f = open("pomo_name.txt", "w")
        f.write(nombre_pomo)
        f.close()
    except:
        pass

# -----------------------------
# HORA
# -----------------------------
def sincronizar_hora_ntp():
    global hora_sincronizada

    if not MQTT_HABILITADO:
        hora_sincronizada = False
        return False

    try:
        ntptime.settime()  # reloj interno queda en UTC
        hora_sincronizada = True
        print("Hora NTP OK:", leer_hora_local())
        return True
    except Exception as e:
        hora_sincronizada = False
        print("No se pudo sincronizar hora:", e)
        return False


def leer_hora_local():
    if not hora_sincronizada:
        return "--:--"

    try:
        t = utime.localtime(utime.time() + UTC_OFFSET_HORAS * 3600)
        return "{:02d}:{:02d}".format(t[3], t[4])
    except:
        return "--:--"


# -----------------------------
# LCD HELPERS
# -----------------------------
def rpad(s, n):
    s = str(s)
    return (s + " " * n)[:n]


def escribir(col, row, texto):
    lcd.set_cursor(col, row)
    lcd.print(str(texto)[:20 - col])


def centrar(texto, row):
    texto = str(texto)[:20]
    col = max((20 - len(texto)) // 2, 0)
    lcd.set_cursor(col, row)
    lcd.print(texto)


def nombre_visible():
    n = nombre_pomo.strip()
    if n:
        return n
    return "POMO"


def cara_mascota(tipo, linea=0):
    caras = MASCOTAS[mascota_idx]["caras"]
    lista = caras.get(tipo, caras["idle"])
    if len(lista) == 1:
        return lista[0]
    return lista[linea % len(lista)]


def dibujar_mascota(tipo, row):
    caras = MASCOTAS[mascota_idx]["caras"].get(tipo, MASCOTAS[mascota_idx]["caras"]["idle"])

    # Si la mascota tiene una sola linea, se dibuja centrada.
    # Si tiene dos, ocupa dos filas.
    if len(caras) == 1:
        centrar(caras[0], row)
    else:
        centrar(caras[0], row)
        if row + 1 < 4:
            centrar(caras[1], row + 1)

def tipo_por_corazones():
    """Estado visual segun vidas/corazones.
    0 corazones  -> triste/llorando hasta completar una sesion.
    1-2 corazones -> neutral.
    3 corazones -> feliz suave.
    4-5 corazones -> muy feliz.
    """
    if vida <= 0:
        return "sad"
    if vida <= 2:
        return "neutral"
    if vida == 3:
        return "idle"
    return "happy"


def dibujar_mascota_compacta(tipo, col, row):
    """Dibuja la mascota en el espacio derecho del menu, sin tapar opciones."""
    caras = MASCOTAS[mascota_idx]["caras"].get(tipo, MASCOTAS[mascota_idx]["caras"]["idle"])
    ancho = 20 - col

    if len(caras) == 1:
        escribir(col, row, rpad(caras[0], ancho))
        if row + 1 < 4:
            escribir(col, row + 1, " " * ancho)
    else:
        escribir(col, row, rpad(caras[0], ancho))
        if row + 1 < 4:
            escribir(col, row + 1, rpad(caras[1], ancho))


# -----------------------------
# AUDIO
# -----------------------------
def beep(frec, ms, duty=350):
    if musica_silenciada:
        utime.sleep_ms(ms)
        return
    if frec == 0:
        buzzer.duty(0)
    else:
        buzzer.freq(frec)
        buzzer.duty(duty)
    utime.sleep_ms(ms)
    buzzer.duty(0)


def melodia(m):
    for nota in m:
        duty = nota[2] if len(nota) > 2 else 350
        beep(nota[0], nota[1], duty)
    buzzer.duty(0)
    gc.collect()


def sonido_interrupcion():
    """Alerta fuerte de interrupcion.
    Respeta Sonido:OFF porque beep() revisa musica_silenciada.
    """
    global menu_musica_sonando
    buzzer.duty(0)
    menu_musica_sonando = False
    melodia(MELODIA_INTERRUPCION)


def actualizar_musica_menu():
    """Musica suave de menu sin bloquear el programa.
    Respeta la opcion Sonido:OFF y se apaga fuera del menu.
    """
    global menu_musica_idx, menu_musica_ms, menu_musica_sonando

    if estado != "menu" or musica_silenciada:
        if menu_musica_sonando:
            buzzer.duty(0)
            menu_musica_sonando = False
        return

    ahora = utime.ticks_ms()

    if menu_musica_ms == 0:
        menu_musica_ms = ahora

    frec, dur = MELODIA_MENU[menu_musica_idx]

    if not menu_musica_sonando:
        if frec == 0:
            buzzer.duty(0)
        else:
            buzzer.freq(frec)
            buzzer.duty(110)  # bajito para que no moleste en el menu
        menu_musica_sonando = True

    if utime.ticks_diff(ahora, menu_musica_ms) >= dur:
        menu_musica_ms = ahora
        menu_musica_idx = (menu_musica_idx + 1) % len(MELODIA_MENU)
        menu_musica_sonando = False

# -----------------------------
# MQTT
# -----------------------------
def chip_id():
    return ubinascii.hexlify(unique_id()).decode()


def wifi_conectar(reiniciar=False):
    global wifi_ok

    if not MQTT_HABILITADO:
        wifi_ok = False
        return False

    gc.collect()
    sta = network.WLAN(network.STA_IF)

    try:
        if reiniciar:
            sta.disconnect()
            sta.active(False)
            utime.sleep_ms(700)
    except Exception as e:
        print("Aviso WiFi:", e)

    try:
        gc.collect()
        sta.active(True)
    except Exception as e:
        print("No se pudo activar WiFi:", e)
        wifi_ok = False
        return False

    if sta.isconnected():
        wifi_ok = True
        return True

    print("Conectando WiFi...")

    try:
        gc.collect()
        sta.connect(WIFI_SSID, WIFI_PASS)
    except Exception as e:
        print("Error WiFi connect:", e)
        wifi_ok = False
        return False

    inicio = utime.ticks_ms()
    while not sta.isconnected():
        utime.sleep_ms(400)
        if utime.ticks_diff(utime.ticks_ms(), inicio) > 18000:
            print("WiFi timeout")
            wifi_ok = False
            return False

    wifi_ok = True
    print("WiFi OK", sta.ifconfig()[0])
    if not hora_sincronizada:
        sincronizar_hora_ntp()
    gc.collect()
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


def mqtt_conectar(reiniciar_wifi=False):
    global mqtt_client, mqtt_ok, mqtt_ultimo_intento_ms, mqtt_ultimo_ping_ms

    if not MQTT_HABILITADO:
        return False

    mqtt_ultimo_intento_ms = utime.ticks_ms()

    if not wifi_conectar(reiniciar_wifi):
        mqtt_ok = False
        return False

    try:
        gc.collect()
        cid = "arcade-" + chip_id()
        mqtt_client = MQTTClient(cid, MQTT_BROKER, port=MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        mqtt_client.set_callback(sub_cb)
        mqtt_client.connect(clean_session=True)
        mqtt_client.subscribe(TOPIC_SUB_COFRE)
        mqtt_ok = True
        mqtt_ultimo_ping_ms = utime.ticks_ms()
        print("MQTT OK")
        mqtt_publicar(TOPIC_PUB_ARCADE, b"conectado")
        # Resincroniza los corazones apenas hay conexion, por si el cofre o
        # Supabase se quedaron con un valor viejo (reinicio, corte de red, etc.).
        mqtt_publicar(TOPIC_PUB_VIDA, str(vida).encode())
        return True
    except Exception as e:
        print("Error MQTT:", e)
        mqtt_marcar_desconectado()
        return False


def mqtt_asegurar_conexion():
    global mqtt_ultimo_intento_ms
    if not MQTT_HABILITADO:
        return False
    if mqtt_client is not None and mqtt_ok:
        return True
    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, mqtt_ultimo_intento_ms) >= MQTT_REINTENTO_MS:
        return mqtt_conectar(False)
    return False


def mqtt_publicar(topic, msg):
    if not mqtt_asegurar_conexion():
        print("MQTT no disponible", topic, msg)
        return False
    try:
        mqtt_client.publish(topic, msg)
        print("Publicado", topic, msg)
        return True
    except Exception as e:
        print("Error publicando:", e)
        mqtt_marcar_desconectado(e)
        return False


def mqtt_loop():
    global mqtt_ultimo_ping_ms
    if not mqtt_asegurar_conexion():
        return
    try:
        mqtt_client.check_msg()
        ahora = utime.ticks_ms()
        if utime.ticks_diff(ahora, mqtt_ultimo_ping_ms) >= MQTT_PING_MS:
            mqtt_client.ping()
            mqtt_ultimo_ping_ms = ahora
            # Reenvio de respaldo: si algun mensaje de vida se perdio (MQTT
            # es QOS0 aqui), esto lo corrige solo cada MQTT_PING_MS.
            mqtt_publicar(TOPIC_PUB_VIDA, str(vida).encode())
    except Exception as e:
        mqtt_marcar_desconectado(e)


def sub_cb(topic, msg):
    global vida, cofre_bloqueado

    print("MQTT recibido", topic, msg)

    if topic != TOPIC_SUB_COFRE:
        return

    if msg == b"bloqueado":
        cofre_bloqueado = True
        # Tambien cuenta si venimos saliendo del descanso y el celular nunca se saco.
        if estado in ("esperando_cofre", "retorno_celular", "verificando_retorno"):
            iniciar_bloque_focus()

    elif msg in (b"celular_presente", b"celular_dentro"):
        # El cofre confirma que el telefono SI esta dentro.
        # No penalizar: solo esperamos a que termine de bloquear.
        if estado in ("retorno_celular", "verificando_retorno"):
            ir_a("verificando_retorno")

    elif msg in (b"celular_ausente", b"celular_fuera"):
        # El cofre confirma que el telefono NO esta dentro al terminar el descanso.
        # Ahora si corre la gracia de 5 segundos para devolverlo.
        if estado == "verificando_retorno":
            iniciar_gracia_retorno()

    elif msg in (b"interrumpido", b"interrupcion"):
        cofre_bloqueado = False
        if estado == "focus":
            ajustar_vida(-1)
            mqtt_publicar(TOPIC_PUB_SESION, b"interrumpida")
            pantalla_temporal("Interrumpido!", "-1 vida", "sad", None, 250)
            sonido_interrupcion()
            utime.sleep_ms(900)
            ir_a("menu")

    elif msg == b"abierto":
        cofre_bloqueado = False
        # Si se abre mientras se estudia, es interrupcion fisica.
        # Si esta en descanso, es apertura normal.
        if estado == "focus":
            ajustar_vida(-1)
            mqtt_publicar(TOPIC_PUB_SESION, b"interrumpida")
            pantalla_temporal("Interrumpido!", "-1 vida", "sad", None, 250)
            sonido_interrupcion()
            utime.sleep_ms(900)
            ir_a("menu")

# -----------------------------
# POMODORO CLASICO
# -----------------------------
def calcular_pomodoros_total(mins):
    return max(1, (mins + POMODORO_CLASICO_MIN - 1) // POMODORO_CLASICO_MIN)


def calcular_seg_focus(bloque_min):
    if MODO_PRESENTACION:
        # Un bloque clasico de 25 min se representa como 60 s.
        return max(10, int(POMODORO_DEMO_SEG * bloque_min / POMODORO_CLASICO_MIN))
    return bloque_min * 60


def calcular_seg_descanso(num_pomodoro):
    if MODO_PRESENTACION:
        return DESCANSO_DEMO_SEG
    if num_pomodoro > 0 and num_pomodoro % POMODOROS_ANTES_DESCANSO_LARGO == 0:
        return DESCANSO_LARGO_MIN * 60
    return DESCANSO_CORTO_MIN * 60


def minutos_modo_cofre():
    # Para demo, el cofre/web registran 1 min por bloque.
    # Para modo real, registran el bloque real: max 25 min.
    if MODO_PRESENTACION:
        return max(1, (calcular_seg_focus(min(POMODORO_CLASICO_MIN, minutos_restantes_total)) + 59) // 60)
    return max(1, min(POMODORO_CLASICO_MIN, minutos_restantes_total))


def iniciar_sesion_total():
    global minutos_restantes_total, pomodoros_hechos, pomodoros_totales, verif_ultimo_ms, verif_intentos
    minutos_restantes_total = minutos_cfg
    pomodoros_hechos = 0
    pomodoros_totales = calcular_pomodoros_total(minutos_cfg)
    verif_ultimo_ms = utime.ticks_ms()
    verif_intentos = 0
    mqtt_publicar(TOPIC_COFRE_COMANDO, ("modo:" + str(minutos_modo_cofre())).encode())
    mqtt_publicar(TOPIC_PUB_ARCADE, b"esperando_celular")
    ir_a("esperando_cofre")


def iniciar_bloque_focus():
    global bloque_actual_min, seg_restantes, ultimo_tick_ms

    if minutos_restantes_total <= 0:
        finalizar_todo()
        return

    bloque_actual_min = min(POMODORO_CLASICO_MIN, minutos_restantes_total)
    seg_restantes = calcular_seg_focus(bloque_actual_min)
    ultimo_tick_ms = utime.ticks_ms()

    mqtt_publicar(TOPIC_PUB_ARCADE, b"estudiando")
    mqtt_publicar(TOPIC_PUB_SESION, b"iniciada")
    ir_a("focus")


def terminar_bloque_focus():
    global minutos_restantes_total, pomodoros_hechos, seg_restantes, vida

    minutos_restantes_total -= bloque_actual_min
    if minutos_restantes_total < 0:
        minutos_restantes_total = 0

    pomodoros_hechos += 1
    ajustar_vida(1)  # recarga 1 vida por Pomodoro completado

    pantalla_temporal("Sesion terminada", "Descanso! Sigue!", "happy", MELODIA_OK, 800)

    seg_restantes = calcular_seg_descanso(pomodoros_hechos)
    mqtt_publicar(TOPIC_PUB_SESION, b"completada")
    mqtt_publicar(TOPIC_PUB_ARCADE, b"descansando")

    # Cambiar a descanso ANTES de abrir para que b"abierto" no sea interrupcion.
    ir_a("descanso")
    mqtt_publicar(TOPIC_COFRE_COMANDO, b"abrir_descanso")
    melodia(MELODIA_DESCANSO_INICIO)


def iniciar_gracia_retorno():
    """Empieza los 5 segundos SOLO cuando el cofre confirma que no hay celular.
    Si el celular nunca se saco durante el descanso, no se penaliza.
    """
    global seg_restantes, ultimo_tick_ms

    seg_restantes = GRACIA_RETORNO_SEG
    ultimo_tick_ms = utime.ticks_ms()
    mqtt_publicar(TOPIC_PUB_ARCADE, b"esperando_retorno")
    ir_a("retorno_celular")


def terminar_descanso():
    global verif_ultimo_ms, verif_intentos
    melodia(MELODIA_DESCANSO_FIN)

    if minutos_restantes_total <= 0:
        finalizar_todo()
        return

    # Queda otro Pomodoro.
    # Se avisa al cofre que termino el descanso.
    # Si el celular sigue dentro, el cofre respondera b"celular_presente" y bloqueara.
    # Si el celular esta fuera, respondera b"celular_ausente" y recien ahi corren los 5 s.
    mqtt_publicar(TOPIC_COFRE_COMANDO, ("modo:" + str(minutos_modo_cofre())).encode())
    mqtt_publicar(TOPIC_COFRE_COMANDO, b"fin_descanso")

    verif_ultimo_ms = utime.ticks_ms()
    verif_intentos = 0
    mqtt_publicar(TOPIC_PUB_ARCADE, b"verificando_retorno")
    ir_a("verificando_retorno")


def finalizar_todo():
    mqtt_publicar(TOPIC_PUB_ARCADE, b"pomodoros_terminados")
    pantalla_temporal("Pomodoros listos!", "Buen trabajo!", "happy", MELODIA_OK, 1600)
    ir_a("menu")


def penalizar_no_retorno():
    ajustar_vida(-1)
    mqtt_publicar(TOPIC_PUB_SESION, b"no_retorno")
    mqtt_publicar(TOPIC_PUB_ARCADE, b"alerta_retorno")
    # Por seguridad, si el cofre llego a cerrarse, lo abrimos.
    # Asi nunca queda el celular encerrado despues de una penalizacion.
    mqtt_publicar(TOPIC_COFRE_COMANDO, b"cancelar")
    pantalla_temporal("No volvio :(", "-1 vida", "sad", None, 250)
    sonido_interrupcion()
    utime.sleep_ms(900)
    ir_a("menu")

# -----------------------------
# PANTALLAS
# -----------------------------
def dibujar_menu():
    lcd.clear()
    hora_txt = leer_hora_local()
    escribir(0, 0, rpad(nombre_visible() + " " + hora_txt, 20))

    # Mostrar 3 opciones visibles para que quepan.
    visibles = 3
    if seleccion == 0:
        inicio = 0
    elif seleccion >= len(OPCIONES) - 1:
        inicio = len(OPCIONES) - visibles
    else:
        inicio = seleccion - 1
    inicio = max(0, inicio)

    for fila in range(3):
        idx = inicio + fila
        if idx >= len(OPCIONES):
            escribir(0, fila + 1, " " * 12)
        else:
            pref = ">" if idx == seleccion else " "
            txt = OPCIONES[idx]
            if txt == "Sonido":
                txt = "Sonido:OFF" if musica_silenciada else "Sonido:ON"
            escribir(0, fila + 1, rpad(pref + txt, 12))

    # Mascota visible en el menu con humor segun corazones.
    dibujar_mascota_compacta(tipo_por_corazones(), 13, 1)
    escribir(13, 3, rpad("V:" + str(vida) + "/" + str(VIDA_MAX), 7))


def modo_nombre():
    return "DEMO" if MODO_PRESENTACION else "POMODORO"


def dibujar_cfg():
    lcd.clear()
    centrar(modo_nombre() + " total", 0)
    centrar("< " + str(minutos_cfg) + " min >", 1)
    if MODO_PRESENTACION:
        centrar("25m = 60s", 2)
    else:
        centrar("25m = 25m real", 2)
    centrar("OK iniciar", 3)


def dibujar_esperando():
    lcd.clear()
    centrar("Pon el celular", 0)
    centrar("en el cofre", 1)
    dibujar_mascota("wait", 2)
    centrar("Manten BACK 5s", 3)


def dibujar_focus():
    lcd.clear()
    m, s = divmod(seg_restantes, 60)
    escribir(0, 0, rpad("Focus {:02d}:{:02d}".format(m, s), 20))
    ciclo = "Pomo {}/{}".format(pomodoros_hechos + 1, pomodoros_totales)
    escribir(0, 1, rpad(ciclo + " R:" + str(minutos_restantes_total) + "m", 20))
    dibujar_mascota("study", 2)
    total = max(1, calcular_seg_focus(bloque_actual_min))
    avance = total - seg_restantes
    bloques = max(0, min(20, avance * 20 // total))
    escribir(0, 3, "#" * bloques + "-" * (20 - bloques))


def dibujar_descanso():
    lcd.clear()
    m, s = divmod(seg_restantes, 60)
    centrar("Descanso!", 0)
    centrar("Sigue asi!", 1)
    centrar("{:02d}:{:02d}".format(m, s), 2)
    dibujar_mascota("rest", 3)


def dibujar_retorno():
    lcd.clear()
    m, s = divmod(seg_restantes, 60)
    centrar("Pon celular", 0)
    centrar("de regreso!", 1)
    centrar("{:02d}:{:02d}".format(m, s), 2)
    dibujar_mascota("wait", 3)


def dibujar_verificando_retorno():
    lcd.clear()
    centrar("Revisando cofre", 0)
    centrar("No saques nada", 1)
    centrar("Si esta dentro", 2)
    centrar("se cerrara solo", 3)


def dibujar_vida():
    lcd.clear()
    centrar("Vitalidad", 0)
    coraz = ("<3 " * vida + ".. " * (VIDA_MAX - vida)).strip()
    centrar(coraz, 1)
    dibujar_mascota(tipo_por_corazones(), 2)
    centrar("BACK volver", 3)


def dibujar_mascota_sel():
    lcd.clear()
    centrar("< " + MASCOTAS[mascota_preview_idx]["nombre"] + " >", 0)
    # Preview simple: usar caras del indice preview.
    caras = MASCOTAS[mascota_preview_idx]["caras"].get("idle")
    if len(caras) == 1:
        centrar(caras[0], 1)
    else:
        centrar(caras[0], 1)
        centrar(caras[1], 2)
    centrar("OK elegir", 3)


def dibujar_nombre():
    lcd.clear()
    centrar("Nombre mascota", 0)
    linea = ""
    for i in range(NAME_LEN):
        letra = nombre_edit[i]
        if letra == " ":
            letra = "_"
        if i == nombre_pos:
            linea += "[" + letra + "]"
        else:
            linea += " " + letra + " "
    centrar(linea, 1)
    centrar("Arr/Ab letra", 2)
    centrar("Iz/Der pos OK", 3)


def dibujar_sistema():
    lcd.clear()
    centrar("Sistema", 0)
    centrar("WiFi:" + ("OK" if wifi_ok else "NO") + " MQTT:" + ("OK" if mqtt_ok else "NO"), 1)
    centrar("LCD addr 39", 2)
    centrar("BACK volver", 3)


def pantalla_temporal(l1, l2, tipo, sonido, ms):
    lcd.clear()
    centrar(l1, 0)
    centrar(l2, 1)
    dibujar_mascota(tipo, 2)
    if sonido:
        melodia(sonido)
    utime.sleep_ms(ms)
    gc.collect()


def dibujar():
    global necesita_dibujar
    if not necesita_dibujar:
        return
    necesita_dibujar = False

    if estado == "menu":
        dibujar_menu()
    elif estado == "cfg":
        dibujar_cfg()
    elif estado == "esperando_cofre":
        dibujar_esperando()
    elif estado == "focus":
        dibujar_focus()
    elif estado == "descanso":
        dibujar_descanso()
    elif estado == "retorno_celular":
        dibujar_retorno()
    elif estado == "verificando_retorno":
        dibujar_verificando_retorno()
    elif estado == "vida":
        dibujar_vida()
    elif estado == "mascota":
        dibujar_mascota_sel()
    elif estado == "nombre":
        dibujar_nombre()
    elif estado == "sistema":
        dibujar_sistema()

# -----------------------------
# INPUT
# -----------------------------
def leer_joystick():
    global ultimo_joy_ms
    xv = joy_x.read()
    yv = joy_y.read()

    direccion = "none"
    if yv < 500:
        direccion = "arriba"
    elif yv > 3500:
        direccion = "abajo"
    elif xv < 500:
        direccion = "derecha"
    elif xv > 3500:
        direccion = "izquierda"

    if direccion == "none":
        ultimo_joy_ms = 0
        return "none"

    ahora = utime.ticks_ms()
    if ultimo_joy_ms == 0 or utime.ticks_diff(ahora, ultimo_joy_ms) >= 230:
        ultimo_joy_ms = ahora
        return direccion
    return "none"


def leer_botones():
    global btn_ok_prev, btn_back_prev, btn_back_down_ms, btn_back_long_fired
    ahora = utime.ticks_ms()
    ok_now = BTN_OK.value()
    back_now = BTN_BACK.value()
    ev = "none"

    # OK al soltar
    if ok_now == 1 and btn_ok_prev == 0:
        utime.sleep_ms(25)
        if BTN_OK.value() == 1:
            ev = "ok"

    # BACK con dos comportamientos:
    # - Mantenido BACK_CANCELAR_MS (5 s) seguido -> "back_largo" (interrumpe sesion).
    #   Se dispara una sola vez, en el momento en que se cumplen los 5 s,
    #   sin esperar a que se suelte el boton.
    # - Toque corto (se suelta antes de los 5 s) -> "back" normal (navegacion).
    if back_now == 0 and btn_back_prev == 1:
        # Recien presionado: empieza a contar.
        btn_back_down_ms = ahora
        btn_back_long_fired = False

    elif back_now == 0 and btn_back_prev == 0 and not btn_back_long_fired:
        # Sigue presionado: revisar si ya se cumplieron los 5 s.
        if btn_back_down_ms != 0 and utime.ticks_diff(ahora, btn_back_down_ms) >= BACK_CANCELAR_MS:
            btn_back_long_fired = True
            ev = "back_largo"

    elif back_now == 1 and btn_back_prev == 0:
        # Se solto el boton.
        if not btn_back_long_fired:
            utime.sleep_ms(25)
            if BTN_BACK.value() == 1:
                ev = "back"
        btn_back_down_ms = 0
        btn_back_long_fired = False

    btn_ok_prev = ok_now
    btn_back_prev = back_now
    return ev


def back_manteniendo_seg_restantes():
    """Cuantos segundos faltan para que se cumpla el hold de BACK.
    Devuelve None si no corresponde mostrar el aviso (no esta presionado,
    ya se disparo el back_largo, o no estamos en un estado de sesion activa).
    """
    if estado not in ESTADOS_SESION_ACTIVA:
        return None
    if btn_back_prev != 0 or btn_back_down_ms == 0 or btn_back_long_fired:
        return None
    transcurrido = utime.ticks_diff(utime.ticks_ms(), btn_back_down_ms)
    restante_ms = BACK_CANCELAR_MS - transcurrido
    if restante_ms <= 0:
        return 0
    return (restante_ms + 999) // 1000


def mostrar_progreso_cancelacion():
    """Mientras se mantiene BACK en un estado de sesion activa, refresca
    en la fila inferior un aviso con la cuenta regresiva del hold."""
    global back_hold_overlay_ms

    restante = back_manteniendo_seg_restantes()
    if restante is None:
        return

    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, back_hold_overlay_ms) < 200:
        return
    back_hold_overlay_ms = ahora
    escribir(0, 3, rpad("Cancelando... {}s".format(restante), 20))


def cambiar_letra(letra, delta):
    if letra not in ALFABETO:
        letra = "A"
    idx = ALFABETO.find(letra)
    return ALFABETO[(idx + delta) % len(ALFABETO)]


def procesar(joy, btn):
    global seleccion, minutos_cfg, musica_silenciada, menu_musica_sonando
    global necesita_dibujar, vida, mascota_idx, mascota_preview_idx
    global nombre_pomo, nombre_edit, nombre_pos, MODO_PRESENTACION

    if estado == "menu":
        if joy == "arriba":
            seleccion = (seleccion - 1) % len(OPCIONES)
            necesita_dibujar = True
        elif joy == "abajo":
            seleccion = (seleccion + 1) % len(OPCIONES)
            necesita_dibujar = True
        elif btn == "ok":
            if seleccion == 0:
                MODO_PRESENTACION = True
                ir_a("cfg")
            elif seleccion == 1:
                MODO_PRESENTACION = False
                ir_a("cfg")
            elif seleccion == 2:
                ir_a("vida")
            elif seleccion == 3:
                mascota_preview_idx = mascota_idx
                ir_a("mascota")
            elif seleccion == 4:
                nombre_edit = list((nombre_pomo + "    ")[:NAME_LEN])
                nombre_pos = 0
                ir_a("nombre")
            elif seleccion == 5:
                musica_silenciada = not musica_silenciada
                buzzer.duty(0)
                menu_musica_sonando = False
                necesita_dibujar = True
            elif seleccion == 6:
                ir_a("sistema")

    elif estado == "cfg":
        if joy == "derecha":
            minutos_cfg = min(120, minutos_cfg + 25)
            necesita_dibujar = True
        elif joy == "izquierda":
            minutos_cfg = max(25, minutos_cfg - 25)
            necesita_dibujar = True
        elif joy in ("arriba", "abajo"):
            MODO_PRESENTACION = not MODO_PRESENTACION
            necesita_dibujar = True
        elif btn == "ok":
            iniciar_sesion_total()
        elif btn == "back":
            ir_a("menu")

    elif estado == "esperando_cofre":
        if btn == "back_largo":
            mqtt_publicar(TOPIC_COFRE_COMANDO, b"cancelar")
            ir_a("menu")

    elif estado == "focus":
        if btn == "back_largo":
            ajustar_vida(-1)
            mqtt_publicar(TOPIC_COFRE_COMANDO, b"cancelar")
            mqtt_publicar(TOPIC_PUB_SESION, b"cancelada")
            pantalla_temporal("Cancelada", "-1 vida", "sad", None, 250)
            sonido_interrupcion()
            utime.sleep_ms(900)
            ir_a("menu")

    elif estado == "descanso":
        if btn == "back_largo":
            ir_a("menu")

    elif estado == "retorno_celular":
        if btn == "back_largo":
            penalizar_no_retorno()

    elif estado == "verificando_retorno":
        if btn == "back_largo":
            mqtt_publicar(TOPIC_COFRE_COMANDO, b"cancelar")
            ir_a("menu")

    elif estado == "vida":
        if btn == "back":
            ir_a("menu")

    elif estado == "mascota":
        if joy in ("derecha", "abajo"):
            mascota_preview_idx = (mascota_preview_idx + 1) % len(MASCOTAS)
            necesita_dibujar = True
        elif joy in ("izquierda", "arriba"):
            mascota_preview_idx = (mascota_preview_idx - 1) % len(MASCOTAS)
            necesita_dibujar = True
        elif btn == "ok":
            mascota_idx = mascota_preview_idx
            guardar_mascota()
            ir_a("menu")
        elif btn == "back":
            ir_a("menu")

    elif estado == "nombre":
        if joy == "derecha":
            nombre_pos = (nombre_pos + 1) % NAME_LEN
            necesita_dibujar = True
        elif joy == "izquierda":
            nombre_pos = (nombre_pos - 1) % NAME_LEN
            necesita_dibujar = True
        elif joy == "arriba":
            nombre_edit[nombre_pos] = cambiar_letra(nombre_edit[nombre_pos], 1)
            necesita_dibujar = True
        elif joy == "abajo":
            nombre_edit[nombre_pos] = cambiar_letra(nombre_edit[nombre_pos], -1)
            necesita_dibujar = True
        elif btn == "ok":
            nombre_pomo = "".join(nombre_edit)
            if nombre_pomo.strip() == "":
                nombre_pomo = "POMO"
            nombre_pomo = (nombre_pomo + "    ")[:NAME_LEN]
            guardar_nombre()
            ir_a("menu")
        elif btn == "back":
            ir_a("menu")

    elif estado == "sistema":
        if btn == "back":
            ir_a("menu")

# -----------------------------
# ESTADOS / TIMER
# -----------------------------
def ir_a(nuevo):
    global estado, necesita_dibujar, ultimo_tick_ms, menu_musica_sonando
    estado = nuevo
    necesita_dibujar = True
    ultimo_tick_ms = utime.ticks_ms()
    if nuevo != "menu":
        buzzer.duty(0)
        menu_musica_sonando = False
    gc.collect()


def actualizar_timer():
    global seg_restantes, ultimo_tick_ms, necesita_dibujar, verif_ultimo_ms, verif_intentos

    # Si estamos esperando que el cofre bloquee, reenvia el modo de respaldo.
    # No inicia focus hasta recibir b"bloqueado".
    if estado == "esperando_cofre":
        ahora = utime.ticks_ms()
        if utime.ticks_diff(ahora, verif_ultimo_ms) >= 4000:
            verif_ultimo_ms = ahora
            verif_intentos += 1
            necesita_dibujar = True
            print("Reenviando modo al cofre", verif_intentos)
            mqtt_publicar(TOPIC_COFRE_COMANDO, ("modo:" + str(minutos_modo_cofre())).encode())
            mqtt_publicar(TOPIC_PUB_ARCADE, b"esperando_celular")
        return

    # En verificacion NO penalizamos. Solo reintentamos preguntarle al cofre.
    # El cofre responde celular_presente/celular_ausente o bloqueado.
    if estado == "verificando_retorno":
        ahora = utime.ticks_ms()
        if utime.ticks_diff(ahora, verif_ultimo_ms) >= 3000:
            verif_ultimo_ms = ahora
            verif_intentos += 1
            necesita_dibujar = True
            print("Reintentando consulta al cofre", verif_intentos)
            mqtt_publicar(TOPIC_COFRE_COMANDO, b"fin_descanso")
        return

    if estado not in ("focus", "descanso", "retorno_celular"):
        return

    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
        ultimo_tick_ms = ahora
        seg_restantes -= 1
        necesita_dibujar = True

        if seg_restantes <= 0:
            if estado == "focus":
                terminar_bloque_focus()
            elif estado == "descanso":
                terminar_descanso()
            elif estado == "retorno_celular":
                penalizar_no_retorno()


def actualizar_anim():
    global frame_idx, anim_tick_ms, necesita_dibujar
    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, anim_tick_ms) >= 900:
        anim_tick_ms = ahora
        frame_idx = 1 - frame_idx
        if estado in ("menu", "esperando_cofre", "focus", "descanso", "retorno_celular", "verificando_retorno", "vida"):
            necesita_dibujar = True

# -----------------------------
# ARRANQUE
# -----------------------------
cargar_archivos()

lcd.clear()
centrar("Hola! Soy " + nombre_visible(), 0)
dibujar_mascota("happy", 1)
centrar("Pomodoro clasico", 3)
utime.sleep_ms(1500)

lcd.clear()
centrar("Conectando WiFi", 1)
dibujar_mascota("wait", 2)

gc.collect()
if MQTT_HABILITADO:
    mqtt_conectar(reiniciar_wifi=True)

gc.collect()
ir_a("menu")
anim_tick_ms = utime.ticks_ms()
ultimo_tick_ms = utime.ticks_ms()

# -----------------------------
# LOOP PRINCIPAL
# -----------------------------
while True:
    mqtt_loop()

    joy = leer_joystick()
    btn = leer_botones()

    if joy != "none" or btn != "none":
        procesar(joy, btn)

    mostrar_progreso_cancelacion()
    actualizar_musica_menu()
    actualizar_timer()
    actualizar_anim()
    dibujar()

    utime.sleep_ms(20)
