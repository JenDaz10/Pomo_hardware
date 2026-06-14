# ============================================================
#  POMO - Mascota Virtual Pomodoro v3
#  ESP32 + LCD I2C 20x4 + Joystick + Botones + Buzzer + RTC
#  Cambios v3:
#    - Botones responden al instante (sin delay double-tap)
#    - Sprites con caracteres personalizados HD44780 (5x8 px)
#    - Menu: opciones izquierda + mascota animada derecha
#    - Silencio movido a pantalla Sistema (OK lo activa)
#    - Long-press BACK -> sleep desde cualquier pantalla
# ============================================================

from machine import Pin, I2C, ADC, PWM, unique_id
from lcd_i2c import LCD
import utime
import ubinascii

# ─────────────────────────────────────────────
#  MQTT / WiFi  (descomentar cuando tengas la red)
# ─────────────────────────────────────────────
MQTT_HABILITADO = False

# import network
# from umqtt.simple import MQTTClient
# WIFI_SSID     = "TuRed"
# WIFI_PASSWORD = "TuClave"
# MQTT_BROKER   = "broker.hivemq.com"
# MQTT_PORT     = 1883
# mqtt_client   = None
# wifi_ok       = False

def obtener_chip_id():
    return ubinascii.hexlify(unique_id()).decode().upper()

def mqtt_conectar():
    if not MQTT_HABILITADO:
        return False
    return False

def mqtt_publicar(topic, msg):
    if not MQTT_HABILITADO:
        return

# ─────────────────────────────────────────────
#  HARDWARE
# ─────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
lcd = LCD(39, 20, 4, i2c=i2c)
lcd.begin()

BTN_OK   = Pin(14, Pin.IN, Pin.PULL_UP)
BTN_BACK = Pin(12, Pin.IN, Pin.PULL_UP)

joy_x = ADC(Pin(34))
joy_y = ADC(Pin(35))
joy_x.atten(ADC.ATTN_11DB)
joy_y.atten(ADC.ATTN_11DB)

buzzer = PWM(Pin(26))
buzzer.duty(0)

RTC_ADDR = 0x68
CHIP_ID  = obtener_chip_id()

# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────
DEBOUNCE_MS   = 25
POLL_MS       = 15
DESCANSO_SEG  = 5 * 60
JOY_REPEAT_MS = 220
LONG_PRESS_MS = 700   # ms para sleep con BACK

OPCIONES = ["Estudiar", "Vitalidad", "Mascota", "Nombre", "Sistema"]

NAME_LEN = 4
ALFABETO = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"

ARCHIVO_MASCOTA = "pomo_pet.txt"
ARCHIVO_NOMBRE  = "pomo_name.txt"

# ─────────────────────────────────────────────
#  NOTAS
# ─────────────────────────────────────────────
A3  = 220
C4  = 261
D4  = 293
E4  = 329
F4  = 349
G4  = 392
A4  = 440
B4  = 494
C5  = 523
D5  = 587
E5  = 659

LOFI_DUTY = 160

MELODIA_LOFI = [
    (D4, 200, LOFI_DUTY), (F4, 150, LOFI_DUTY), (A4, 300, LOFI_DUTY), (0, 100, 0),
    (C5, 200, LOFI_DUTY), (A4, 150, LOFI_DUTY), (0,  200, 0),
    (G4, 200, LOFI_DUTY), (B4, 150, LOFI_DUTY), (D5, 300, LOFI_DUTY), (0, 150, 0),
    (E4, 200, LOFI_DUTY), (G4, 150, LOFI_DUTY), (0,  200, 0),
    (C4, 200, LOFI_DUTY), (E4, 150, LOFI_DUTY), (G4, 200, LOFI_DUTY), (A4, 350, LOFI_DUTY), (0, 200, 0),
    (A3, 200, LOFI_DUTY), (C4, 150, LOFI_DUTY), (E4, 300, LOFI_DUTY), (G4, 200, LOFI_DUTY), (0, 500, 0),
]

MELODIA_TRIUNFO  = [(C4,120),(E4,120),(G4,120),(C5,320),(0,80)]
MELODIA_TRISTE   = [(G4,230),(F4,230),(E4,230),(D4,450),(0,80)]
MELODIA_SLEEP    = [(A4,200),(G4,200),(E4,400),(0,200)]
MELODIA_WAKE     = [(E4,200),(G4,200),(A4,400),(0,100)]

# ─────────────────────────────────────────────
#  CARACTERES PERSONALIZADOS HD44780
#  El LCD tiene 8 slots (indices 0-7)
#  Cada caracter es una lista de 8 bytes (filas 5 bits)
#
#  Usamos 6 slots:
#   0,1,2 = fila superior de la mascota (3 caracteres de ancho)
#   3,4,5 = fila inferior de la mascota
#
#  Cada mascota tiene 2 frames (idle_a, idle_b) y estados
#  Formato: { "estado": { "top": [[c0,c1,c2],[c0,c1,c2]], "bot": [[c3,c4,c5],[...]] } }
#  donde cada lista tiene 2 frames (animacion)
# ─────────────────────────────────────────────

# Helper: convierte lista de strings de 5 chars a lista de bytes
def _b(filas):
    resultado = []
    for f in filas:
        val = 0
        for i, ch in enumerate(f[:5]):
            if ch != ' ':
                val |= (1 << (4 - i))
        resultado.append(val)
    while len(resultado) < 8:
        resultado.append(0)
    return resultado[:8]

# ── GATO ──────────────────────────────────────
# Top: 3 chars de ancho = 15 px, altura top 3 filas
# Bot: altura bot 5 filas (usa filas 0-7 del slot)
# Char 0: oreja+cabeza izq   Char 1: cabeza centro   Char 2: oreja+cabeza der
# Char 3: cuerpo izq         Char 4: cuerpo centro   Char 5: cuerpo der

GATO_TOP_A = [
    _b(["## ##","#####","#####","## ##","#####","## ##","     ","     "]),  # char0: orejas+lado izq
    _b(["     ","     ","o   o","  o  "," --- ","     ","     ","     "]),  # char1: cara ojos abiertos
    _b(["## ##","#####","#####","## ##","#####","## ##","     ","     "]),  # char2: orejas+lado der (igual 0)
]
GATO_TOP_B = [
    _b(["## ##","#####","#####","## ##","#####","## ##","     ","     "]),
    _b(["     ","     ","- - -","  o  "," --- ","     ","     ","     "]),  # char1: ojos semicerrados
    _b(["## ##","#####","#####","## ##","#####","## ##","     ","     "]),
]
GATO_BOT_A = [
    _b(["#####","#   #","#   #","#   #"," ### ","     ","     ","     "]),  # char3: pata izq
    _b(["#####","  #  ","  #  ","  #  "," # # ","     ","     ","     "]),  # char4: cola centro
    _b(["#####","#   #","#   #","#   #"," ### ","     ","     ","     "]),  # char5: pata der
]
# Frame B cuerpo igual (solo cambia la cara)
GATO_BOT_B = GATO_BOT_A

# ── POLLO ─────────────────────────────────────
POLLO_TOP_A = [
    _b(["  ## ","  ###","#####","## ##","#####","     ","     ","     "]),
    _b(["  ## ","#    ","o   o","  ^  "," --- ","     ","     ","     "]),  # pico abierto
    _b([" ## ","###  ","#####","## ##","#####","     ","     ","     "]),
]
POLLO_TOP_B = [
    _b(["  ## ","  ###","#####","## ##","#####","     ","     ","     "]),
    _b(["  ## ","#    ","- - -","  ^  "," --- ","     ","     ","     "]),  # pico cerrado
    _b([" ## ","###  ","#####","## ##","#####","     ","     ","     "]),
]
POLLO_BOT_A = [
    _b(["#####"," ### "," # # ","  #  ","  #  ","     ","     ","     "]),
    _b(["#####"," ### "," ### ","  #  "," # # ","     ","     ","     "]),
    _b(["#####"," ### "," # # ","  #  ","  #  ","     ","     ","     "]),
]
POLLO_BOT_B = POLLO_BOT_A

# ── BLOB ──────────────────────────────────────
BLOB_TOP_A = [
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
    _b(["     ","     ","o   o","     "," --- ","     ","     ","     "]),
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
]
BLOB_TOP_B = [
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
    _b(["     ","     ","- - -","     "," --- ","     ","     ","     "]),
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
]
BLOB_BOT_A = [
    _b(["#####","#####","#####"," ### ","     ","     ","     ","     "]),
    _b(["#####","#####","#####"," ### ","     ","     ","     ","     "]),
    _b(["#####","#####","#####"," ### ","     ","     ","     ","     "]),
]
BLOB_BOT_B = BLOB_BOT_A

# ── FANTASMA ──────────────────────────────────
FANT_TOP_A = [
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
    _b(["     ","     ","o   o","     ","  -  ","     ","     ","     "]),
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
]
FANT_TOP_B = [
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
    _b(["     ","     ","- - -","     ","  -  ","     ","     ","     "]),
    _b([" ### ","#####","#####","#####","#####","     ","     ","     "]),
]
FANT_BOT_A = [
    _b(["#####","#####","#####","## ##","     ","     ","     ","     "]),
    _b(["#####","#####","#####","## ##","     ","     ","     ","     "]),
    _b(["#####","#####","#####","## ##","     ","     ","     ","     "]),
]
FANT_BOT_B = FANT_BOT_A

# ── SLEEP (compartido, sobreescribe char1 y char4) ──
SLEEP_TOP_MID = _b(["     ","  z  "," z   ","z    ","     ","     ","     ","     "])
SLEEP_BOT_MID = _b(["     ","  z  "," z   ","z    ","     ","     ","     ","     "])

# ── ESTUDIO (cara concentrada, sobreescribe char1) ──
STUDY_FACE   = _b(["     ","     ","## ##","  o  "," --- ","     ","     ","     "])
# ── FELIZ ──
HAPPY_FACE   = _b(["     ","     ","o   o","     ","#####","     ","     ","     "])
# ── TRISTE ──
SAD_FACE     = _b(["     ","     ","o   o","     ","#####","     ","     ","     "])  # igual, boca invertida se hace en texto

MASCOTAS = [
    {
        "nombre": "Gato",
        "custom": {
            "idle":  {"top": [GATO_TOP_A, GATO_TOP_B],  "bot": [GATO_BOT_A, GATO_BOT_B]},
            "study": {"top": [GATO_TOP_A, GATO_TOP_A],  "bot": [GATO_BOT_A, GATO_BOT_A]},
            "happy": {"top": [GATO_TOP_A, GATO_TOP_B],  "bot": [GATO_BOT_A, GATO_BOT_B]},
            "rest":  {"top": [GATO_TOP_B, GATO_TOP_B],  "bot": [GATO_BOT_B, GATO_BOT_B]},
            "sad":   {"top": [GATO_TOP_B, GATO_TOP_A],  "bot": [GATO_BOT_A, GATO_BOT_B]},
            "sleep": {"top": [GATO_TOP_B, GATO_TOP_B],  "bot": [GATO_BOT_B, GATO_BOT_B]},
        }
    },
    {
        "nombre": "Pollo",
        "custom": {
            "idle":  {"top": [POLLO_TOP_A, POLLO_TOP_B], "bot": [POLLO_BOT_A, POLLO_BOT_B]},
            "study": {"top": [POLLO_TOP_A, POLLO_TOP_A], "bot": [POLLO_BOT_A, POLLO_BOT_A]},
            "happy": {"top": [POLLO_TOP_A, POLLO_TOP_B], "bot": [POLLO_BOT_A, POLLO_BOT_B]},
            "rest":  {"top": [POLLO_TOP_B, POLLO_TOP_B], "bot": [POLLO_BOT_B, POLLO_BOT_B]},
            "sad":   {"top": [POLLO_TOP_B, POLLO_TOP_A], "bot": [POLLO_BOT_A, POLLO_BOT_B]},
            "sleep": {"top": [POLLO_TOP_B, POLLO_TOP_B], "bot": [POLLO_BOT_B, POLLO_BOT_B]},
        }
    },
    {
        "nombre": "Blob",
        "custom": {
            "idle":  {"top": [BLOB_TOP_A, BLOB_TOP_B], "bot": [BLOB_BOT_A, BLOB_BOT_B]},
            "study": {"top": [BLOB_TOP_A, BLOB_TOP_A], "bot": [BLOB_BOT_A, BLOB_BOT_A]},
            "happy": {"top": [BLOB_TOP_A, BLOB_TOP_B], "bot": [BLOB_BOT_A, BLOB_BOT_B]},
            "rest":  {"top": [BLOB_TOP_B, BLOB_TOP_B], "bot": [BLOB_BOT_B, BLOB_BOT_B]},
            "sad":   {"top": [BLOB_TOP_B, BLOB_TOP_A], "bot": [BLOB_BOT_A, BLOB_BOT_B]},
            "sleep": {"top": [BLOB_TOP_B, BLOB_TOP_B], "bot": [BLOB_BOT_B, BLOB_BOT_B]},
        }
    },
    {
        "nombre": "Fant",
        "custom": {
            "idle":  {"top": [FANT_TOP_A, FANT_TOP_B], "bot": [FANT_BOT_A, FANT_BOT_B]},
            "study": {"top": [FANT_TOP_A, FANT_TOP_A], "bot": [FANT_BOT_A, FANT_BOT_A]},
            "happy": {"top": [FANT_TOP_A, FANT_TOP_B], "bot": [FANT_BOT_A, FANT_BOT_B]},
            "rest":  {"top": [FANT_TOP_B, FANT_TOP_B], "bot": [FANT_BOT_B, FANT_BOT_B]},
            "sad":   {"top": [FANT_TOP_B, FANT_TOP_A], "bot": [FANT_BOT_A, FANT_BOT_B]},
            "sleep": {"top": [FANT_TOP_B, FANT_TOP_B], "bot": [FANT_BOT_B, FANT_BOT_B]},
        }
    },
]

# ─────────────────────────────────────────────
#  CGRAM: cargar caracteres personalizados en el LCD
#  El chip HD44780 permite 8 caracteres custom (slots 0-7)
#  Usamos slots 0-5 para la mascota (3 top + 3 bot)
# ─────────────────────────────────────────────
_cg_cargado_idx   = -1
_cg_cargado_frame = -1
_cg_cargado_tipo  = ""

def cargar_cgram(idx_mascota, tipo, frame):
    """Carga los 6 caracteres de la mascota en la CGRAM del LCD.
       Solo escribe si cambiaron para no parpadear."""
    global _cg_cargado_idx, _cg_cargado_frame, _cg_cargado_tipo

    if (_cg_cargado_idx   == idx_mascota and
        _cg_cargado_frame == frame and
        _cg_cargado_tipo  == tipo):
        return   # nada que actualizar

    _cg_cargado_idx   = idx_mascota
    _cg_cargado_frame = frame
    _cg_cargado_tipo  = tipo

    data = MASCOTAS[idx_mascota]["custom"].get(tipo)
    if data is None:
        data = MASCOTAS[idx_mascota]["custom"]["idle"]

    tops = data["top"][frame % 2]   # lista de 3 listas de 8 bytes
    bots = data["bot"][frame % 2]

    # El controlador HD44780 recibe comandos I2C via la libreria lcd_i2c
    # lcd.create_char(slot, [8 bytes]) — verifica que tu libreria lo tenga
    for slot in range(3):
        lcd.create_char(slot,     tops[slot])
    for slot in range(3):
        lcd.create_char(slot + 3, bots[slot])

def dibujar_cgram_mascota(col, row_top):
    """Pone los 6 caracteres custom en col,row_top y col,row_top+1"""
    for c in range(3):
        lcd.set_cursor(col + c, row_top)
        lcd.print(chr(c))           # char custom 0,1,2
    for c in range(3):
        lcd.set_cursor(col + c, row_top + 1)
        lcd.print(chr(c + 3))       # char custom 3,4,5

# ─────────────────────────────────────────────
#  GUARDAR / CARGAR
# ─────────────────────────────────────────────
def cargar_mascota():
    try:
        f = open(ARCHIVO_MASCOTA, "r")
        valor = int(f.read())
        f.close()
        if 0 <= valor < len(MASCOTAS):
            return valor
    except:
        pass
    return 0

def guardar_mascota(indice):
    try:
        f = open(ARCHIVO_MASCOTA, "w")
        f.write(str(indice))
        f.close()
    except:
        pass

def cargar_nombre():
    try:
        f = open(ARCHIVO_NOMBRE, "r")
        texto = f.read().replace("\n","").replace("\r","").upper()
        f.close()
        limpio = "".join(c for c in texto if c in ALFABETO)
        limpio = (limpio + "    ")[:NAME_LEN]
        if limpio.strip():
            return limpio
    except:
        pass
    return "POMO"

def guardar_nombre(nombre):
    try:
        f = open(ARCHIVO_NOMBRE, "w")
        f.write(nombre)
        f.close()
    except:
        pass

# ─────────────────────────────────────────────
#  ESTADO GLOBAL
# ─────────────────────────────────────────────
estado           = "menu"
seleccion        = 0
vida             = 3
minutos_cfg      = 25
seg_restantes    = 0

necesita_dibujar = True
ultimo_tick_ms   = 0
anim_tick_ms     = 0
frame_idx        = 0
ultimo_joy_ms    = 0

mascota_idx         = cargar_mascota()
mascota_preview_idx = mascota_idx

nombre_pomo = cargar_nombre()
nombre_edit = list(nombre_pomo)
nombre_pos  = 0

musica_silenciada = False
durmiendo         = False

nota_lofi_idx  = 0
tiempo_nota_ms = 0

# Botones: deteccion por flanco simple (sin double-tap)
btn_ok_prev      = 1
btn_back_prev    = 1
btn_back_down_ms = 0

mqtt_ok = False

# ─────────────────────────────────────────────
#  AUDIO
# ─────────────────────────────────────────────
def beep_bloq(frec, ms, duty=400):
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

def reproducir_melodia_bloqueante(melodia):
    for item in melodia:
        frec, ms = item[0], item[1]
        duty = item[2] if len(item) > 2 else 400
        beep_bloq(frec, ms, duty)
    buzzer.duty(0)

def actualizar_musica_lofi():
    global nota_lofi_idx, tiempo_nota_ms

    if estado != "menu" or durmiendo or musica_silenciada:
        buzzer.duty(0)
        return

    ahora = utime.ticks_ms()
    duracion = MELODIA_LOFI[nota_lofi_idx][1]

    if utime.ticks_diff(ahora, tiempo_nota_ms) >= duracion:
        tiempo_nota_ms = ahora
        nota_lofi_idx  = (nota_lofi_idx + 1) % len(MELODIA_LOFI)
        frec = MELODIA_LOFI[nota_lofi_idx][0]
        duty = MELODIA_LOFI[nota_lofi_idx][2]
        if frec == 0:
            buzzer.duty(0)
        else:
            buzzer.freq(frec)
            buzzer.duty(duty)

# ─────────────────────────────────────────────
#  RTC
# ─────────────────────────────────────────────
def leer_hora_rtc():
    try:
        i2c.writeto(RTC_ADDR, b'\x00')
        data = i2c.readfrom(RTC_ADDR, 3)
        ss = (data[0] & 0x0F) + ((data[0] >> 4) * 10)
        mm = (data[1] & 0x0F) + ((data[1] >> 4) * 10)
        hh = (data[2] & 0x0F) + (((data[2] & 0x30) >> 4) * 10)
        return "{:02d}:{:02d}".format(hh, mm)
    except:
        return "--:--"

# ─────────────────────────────────────────────
#  LCD helpers
# ─────────────────────────────────────────────
def rpad(s, n):
    s = str(s)
    return (s + " " * n)[:n]

def centrar(texto, row, ancho=20):
    texto = str(texto)[:ancho]
    pad = max((ancho - len(texto)) // 2, 0)
    lcd.set_cursor(pad, row)
    lcd.print(texto)

def escribir(col, row, texto):
    lcd.set_cursor(col, row)
    lcd.print(str(texto)[:20 - col])

def nombre_visible():
    n = nombre_pomo.strip()
    return n if n else "POMO"

def nombre_mascota_txt(idx=None):
    if idx is None:
        idx = mascota_idx
    return MASCOTAS[idx]["nombre"]

# ─────────────────────────────────────────────
#  PANTALLAS
# ─────────────────────────────────────────────

def dibujar_menu():
    """Layout: cols 0-11 opciones | cols 13-15 mascota custom (3 chars ancho x 2 alto)
       Fila 0: NOMBRE  HORA    (encabezado completo)
       Fila 1: >opcion  [C0][C1][C2]
       Fila 2:  opcion  [C3][C4][C5]
       Fila 3:  opcion  (mascota name)
    """
    lcd.clear()

    # ── Encabezado fila 0 ──
    hora = leer_hora_rtc()
    sil  = "x" if musica_silenciada else " "
    # NOMBRE(4) + espacio + silencio + hora(5) = 12 chars, resto espacio
    hdr = rpad(nombre_visible(), 4) + " " + sil + " " + hora
    escribir(0, 0, rpad(hdr, 20))

    # ── Opciones filas 1-3 (solo primeras 12 cols) ──
    visibles = 3
    if seleccion == 0:
        inicio = 0
    elif seleccion >= len(OPCIONES) - 1:
        inicio = len(OPCIONES) - visibles
    else:
        inicio = seleccion - 1
    inicio = max(inicio, 0)

    for fila in range(3):
        idx = inicio + fila
        if idx >= len(OPCIONES):
            escribir(0, fila + 1, " " * 12)
        else:
            prefijo = ">" if idx == seleccion else " "
            texto = rpad(prefijo + OPCIONES[idx], 12)
            escribir(0, fila + 1, texto)

    # ── Mascota custom cols 13-15, filas 1-2 ──
    cargar_cgram(mascota_idx, "idle", frame_idx)
    dibujar_cgram_mascota(13, 1)

    # Nombre mascota fila 3 cols 13+
    escribir(13, 3, rpad(nombre_mascota_txt(), 7))


def dibujar_estudiar_cfg():
    lcd.clear()
    centrar("-- Configurar --", 0)
    centrar("Tiempo estudio:", 1)
    centrar("< " + str(minutos_cfg) + " min >", 2)
    centrar("[OK] iniciar", 3)

def dibujar_estudiar_run():
    lcd.clear()
    m, s = divmod(seg_restantes, 60)
    hora_txt = "Focus {:02d}:{:02d}".format(m, s)
    escribir(0, 0, rpad(hora_txt, 12))
    # barra de progreso simple cols 0-11 fila 3
    total    = minutos_cfg * 60
    avance   = total - seg_restantes
    bloques  = avance * 12 // total
    barra    = "#" * bloques + "-" * (12 - bloques)
    escribir(0, 3, barra)
    # mascota cols 13-15 filas 1-2
    cargar_cgram(mascota_idx, "study", frame_idx)
    dibujar_cgram_mascota(13, 1)

def dibujar_descanso_run():
    lcd.clear()
    m, s = divmod(seg_restantes, 60)
    escribir(0, 0, rpad("Descanso {:02d}:{:02d}".format(m,s), 12))
    total   = DESCANSO_SEG
    avance  = total - seg_restantes
    bloques = avance * 12 // total
    barra   = "#" * bloques + "-" * (12 - bloques)
    escribir(0, 3, barra)
    cargar_cgram(mascota_idx, "rest", frame_idx)
    dibujar_cgram_mascota(13, 1)

def dibujar_vida():
    lcd.clear()
    pct = vida * 100 // 3
    centrar("Vitalidad: " + str(pct) + "%", 0)
    coraz = ("<3 " * vida + ".. " * (3 - vida)).strip()
    centrar(coraz, 1)
    cargar_cgram(mascota_idx, "idle" if vida > 1 else "sad", frame_idx)
    dibujar_cgram_mascota(8, 2)
    centrar("[BACK] volver", 3)

def dibujar_mascota_sel():
    lcd.clear()
    nombre = nombre_mascota_txt(mascota_preview_idx)
    centrar("< " + nombre + " >", 0)
    cargar_cgram(mascota_preview_idx, "idle", frame_idx)
    # Mascota centrada en pantalla: cols 8-10, filas 1-2
    dibujar_cgram_mascota(8, 1)
    centrar("[OK] elegir", 3)

def dibujar_nombre():
    lcd.clear()
    centrar("Nombre mascota", 0)
    linea = ""
    for i in range(NAME_LEN):
        letra = nombre_edit[i]
        if letra == " ":
            letra = "_"
        linea += ("[" + letra + "]") if i == nombre_pos else (" " + letra + " ")
    centrar(linea, 1)
    centrar("Arr/Ab = letra", 2)
    centrar("Iz/Der = pos  OK", 3)

def dibujar_sistema():
    lcd.clear()
    centrar("-- Sistema --", 0)
    cid = CHIP_ID
    centrar("ID:" + cid[:8], 1)
    mqtt_txt = "MQTT:ON" if (mqtt_ok and MQTT_HABILITADO) else "MQTT:OFF"
    sil_txt  = " Sil:SI" if musica_silenciada else " Sil:NO"
    centrar(mqtt_txt + sil_txt, 2)
    centrar("OK=sil  BACK=volver", 3)

def dibujar_sesion_ok():
    lcd.clear()
    centrar("Sesion completa!", 0)
    centrar("    +1 vida!    ", 1)
    cargar_cgram(mascota_idx, "happy", 0)
    dibujar_cgram_mascota(8, 2)

def dibujar_sesion_cancelada():
    lcd.clear()
    centrar("Cancelada :(", 0)
    centrar("   -1 vida...   ", 1)
    cargar_cgram(mascota_idx, "sad", 0)
    dibujar_cgram_mascota(8, 2)

def dibujar_sleep():
    lcd.clear()
    centrar("  z z z . . .  ", 0)
    cargar_cgram(mascota_idx, "sleep", frame_idx)
    dibujar_cgram_mascota(8, 1)
    centrar(nombre_visible(), 3)

# ─────────────────────────────────────────────
#  SLEEP MODE
# ─────────────────────────────────────────────
def entrar_sleep():
    global durmiendo, necesita_dibujar
    durmiendo = True
    necesita_dibujar = True
    buzzer.duty(0)
    reproducir_melodia_bloqueante(MELODIA_SLEEP)

def salir_sleep():
    global durmiendo, necesita_dibujar
    durmiendo = False
    necesita_dibujar = True
    reproducir_melodia_bloqueante(MELODIA_WAKE)

# ─────────────────────────────────────────────
#  LECTURA JOYSTICK
# ─────────────────────────────────────────────
def leer_joystick():
    global ultimo_joy_ms

    xv = joy_x.read()
    yv = joy_y.read()

    direccion = "none"
    if   yv < 500:  direccion = "arriba"
    elif yv > 3500: direccion = "abajo"
    elif xv < 500:  direccion = "derecha"
    elif xv > 3500: direccion = "izquierda"

    if direccion == "none":
        ultimo_joy_ms = 0
        return "none"

    ahora = utime.ticks_ms()
    if ultimo_joy_ms == 0 or utime.ticks_diff(ahora, ultimo_joy_ms) >= JOY_REPEAT_MS:
        ultimo_joy_ms = ahora
        return direccion
    return "none"

# ─────────────────────────────────────────────
#  LECTURA BOTONES — flanco simple, sin double-tap
#  OK  -> dispara al SOLTAR (evita rebotes largos)
#  BACK short -> al soltar
#  BACK long  -> al superar LONG_PRESS_MS (sin soltar)
# ─────────────────────────────────────────────
def leer_botones():
    global btn_ok_prev, btn_back_prev, btn_back_down_ms

    ahora    = utime.ticks_ms()
    ok_now   = BTN_OK.value()
    back_now = BTN_BACK.value()
    evento   = ("none", "none")

    # OK: flanco de SUBIDA (soltar) = press confirmado
    if ok_now == 1 and btn_ok_prev == 0:
        utime.sleep_ms(DEBOUNCE_MS)
        if BTN_OK.value() == 1:
            evento = ("ok", "press")

    # BACK: registrar cuando baja
    if back_now == 0 and btn_back_prev == 1:
        utime.sleep_ms(DEBOUNCE_MS)
        if BTN_BACK.value() == 0:
            btn_back_down_ms = ahora

    # BACK long: detectar mientras sigue presionado
    if back_now == 0 and btn_back_down_ms > 0:
        if utime.ticks_diff(ahora, btn_back_down_ms) >= LONG_PRESS_MS:
            btn_back_down_ms = 0
            evento = ("back", "long")

    # BACK short: al soltar antes del long
    if back_now == 1 and btn_back_prev == 0:
        utime.sleep_ms(DEBOUNCE_MS)
        if BTN_BACK.value() == 1 and btn_back_down_ms > 0:
            btn_back_down_ms = 0
            evento = ("back", "press")

    btn_ok_prev   = ok_now
    btn_back_prev = back_now
    return evento

# ─────────────────────────────────────────────
#  CAMBIO DE ESTADO
# ─────────────────────────────────────────────
def ir_a(nuevo):
    global estado, necesita_dibujar, seg_restantes, ultimo_tick_ms, _cg_cargado_tipo

    estado = nuevo
    necesita_dibujar = True
    _cg_cargado_tipo = ""  # forzar recarga de CGRAM al cambiar pantalla

    if nuevo == "estudiar_run":
        seg_restantes  = minutos_cfg * 60
        ultimo_tick_ms = utime.ticks_ms()
    elif nuevo == "descanso_run":
        seg_restantes  = DESCANSO_SEG
        ultimo_tick_ms = utime.ticks_ms()

def cambiar_letra(letra, delta):
    if letra not in ALFABETO:
        letra = "A"
    idx = ALFABETO.find(letra)
    return ALFABETO[(idx + delta) % len(ALFABETO)]

# ─────────────────────────────────────────────
#  PROCESAR EVENTOS
# ─────────────────────────────────────────────
def procesar_evento(joy, btn_id, btn_tipo):
    global seleccion, minutos_cfg, vida
    global mascota_idx, mascota_preview_idx
    global nombre_pomo, nombre_edit, nombre_pos
    global necesita_dibujar, musica_silenciada

    # Sleep: cualquier boton despierta
    if durmiendo:
        if btn_tipo in ("press", "long"):
            salir_sleep()
        return

    # Long press BACK -> sleep desde cualquier estado
    if btn_id == "back" and btn_tipo == "long":
        entrar_sleep()
        return

    # ── Menu ──
    if estado == "menu":
        if joy == "arriba":
            seleccion = (seleccion - 1) % len(OPCIONES)
            necesita_dibujar = True
        elif joy == "abajo":
            seleccion = (seleccion + 1) % len(OPCIONES)
            necesita_dibujar = True
        elif btn_id == "ok" and btn_tipo == "press":
            if   seleccion == 0: ir_a("estudiar_cfg")
            elif seleccion == 1: ir_a("vida")
            elif seleccion == 2:
                mascota_preview_idx = mascota_idx
                ir_a("mascota")
            elif seleccion == 3:
                nombre_edit = list(nombre_pomo)
                nombre_pos  = 0
                ir_a("nombre")
            elif seleccion == 4: ir_a("sistema")

    # ── Configurar tiempo ──
    elif estado == "estudiar_cfg":
        if   joy == "derecha":   minutos_cfg = min(minutos_cfg + 5, 60); necesita_dibujar = True
        elif joy == "izquierda": minutos_cfg = max(minutos_cfg - 5, 5);  necesita_dibujar = True
        elif btn_id == "ok"   and btn_tipo == "press": ir_a("estudiar_run")
        elif btn_id == "back" and btn_tipo == "press": ir_a("menu")

    # ── Sesion focus ──
    elif estado == "estudiar_run":
        if btn_id == "back" and btn_tipo == "press":
            vida = max(vida - 1, 0)
            buzzer.duty(0)
            dibujar_sesion_cancelada()
            reproducir_melodia_bloqueante(MELODIA_TRISTE)
            mqtt_publicar(b"pomo/status", b"cancelled")
            mqtt_publicar(b"pomo/vida",   str(vida).encode())
            ir_a("menu")

    # ── Descanso ──
    elif estado == "descanso_run":
        if btn_id == "back" and btn_tipo == "press": ir_a("menu")

    # ── Vitalidad ──
    elif estado == "vida":
        if btn_id == "back" and btn_tipo == "press": ir_a("menu")

    # ── Elegir mascota ──
    elif estado == "mascota":
        if joy in ("derecha", "abajo"):
            mascota_preview_idx = (mascota_preview_idx + 1) % len(MASCOTAS)
            necesita_dibujar = True
        elif joy in ("izquierda", "arriba"):
            mascota_preview_idx = (mascota_preview_idx - 1) % len(MASCOTAS)
            necesita_dibujar = True
        elif btn_id == "ok" and btn_tipo == "press":
            mascota_idx = mascota_preview_idx
            guardar_mascota(mascota_idx)
            ir_a("menu")
        elif btn_id == "back" and btn_tipo == "press":
            ir_a("menu")

    # ── Nombre ──
    elif estado == "nombre":
        if   joy == "derecha":   nombre_pos = (nombre_pos + 1) % NAME_LEN; necesita_dibujar = True
        elif joy == "izquierda": nombre_pos = (nombre_pos - 1) % NAME_LEN; necesita_dibujar = True
        elif joy == "arriba":    nombre_edit[nombre_pos] = cambiar_letra(nombre_edit[nombre_pos], 1);  necesita_dibujar = True
        elif joy == "abajo":     nombre_edit[nombre_pos] = cambiar_letra(nombre_edit[nombre_pos], -1); necesita_dibujar = True
        elif btn_id == "ok" and btn_tipo == "press":
            nombre_pomo = "".join(nombre_edit)
            if nombre_pomo.strip() == "":
                nombre_pomo = "POMO"
            nombre_pomo = (nombre_pomo + "    ")[:NAME_LEN]
            guardar_nombre(nombre_pomo)
            ir_a("menu")
        elif btn_id == "back" and btn_tipo == "press":
            ir_a("menu")

    # ── Sistema ──
    elif estado == "sistema":
        if btn_id == "ok" and btn_tipo == "press":
            musica_silenciada = not musica_silenciada
            buzzer.duty(0)
            necesita_dibujar = True
        elif btn_id == "back" and btn_tipo == "press":
            ir_a("menu")

# ─────────────────────────────────────────────
#  TIMER Y ANIMACION
# ─────────────────────────────────────────────
def actualizar_temporizador():
    global seg_restantes, ultimo_tick_ms, necesita_dibujar, vida

    ahora = utime.ticks_ms()

    if estado == "menu":
        if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
            ultimo_tick_ms   = ahora
            necesita_dibujar = True
        return

    if estado not in ("estudiar_run", "descanso_run"):
        return

    if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
        ultimo_tick_ms   = ahora
        seg_restantes   -= 1
        necesita_dibujar = True

        if seg_restantes <= 0:
            if estado == "estudiar_run":
                vida = min(vida + 1, 3)
                dibujar_sesion_ok()
                reproducir_melodia_bloqueante(MELODIA_TRIUNFO)
                mqtt_publicar(b"pomo/status", b"finished")
                mqtt_publicar(b"pomo/vida",   str(vida).encode())
                ir_a("descanso_run")
            else:
                ir_a("menu")

def actualizar_animacion():
    global frame_idx, anim_tick_ms, necesita_dibujar

    intervalo = 600 if estado in ("mascota", "vida") else 450
    ahora = utime.ticks_ms()

    if utime.ticks_diff(ahora, anim_tick_ms) >= intervalo:
        anim_tick_ms = ahora
        frame_idx = 1 - frame_idx
        necesita_dibujar = True   # la mascota siempre puede animar

# ─────────────────────────────────────────────
#  DIBUJO
# ─────────────────────────────────────────────
def dibujar():
    global necesita_dibujar

    if not necesita_dibujar:
        return
    necesita_dibujar = False

    if durmiendo:
        dibujar_sleep()
        return

    if   estado == "menu":          dibujar_menu()
    elif estado == "estudiar_cfg":  dibujar_estudiar_cfg()
    elif estado == "estudiar_run":  dibujar_estudiar_run()
    elif estado == "descanso_run":  dibujar_descanso_run()
    elif estado == "vida":          dibujar_vida()
    elif estado == "mascota":       dibujar_mascota_sel()
    elif estado == "nombre":        dibujar_nombre()
    elif estado == "sistema":       dibujar_sistema()

# ─────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────
lcd.clear()
# Splash: usar chars custom para mostrar la mascota
cargar_cgram(mascota_idx, "happy", 0)
centrar("  Hola! Soy  ", 0)
dibujar_cgram_mascota(8, 1)
centrar(nombre_visible(), 3)
utime.sleep_ms(1800)

if MQTT_HABILITADO:
    lcd.clear()
    centrar("Conectando...", 1)
    mqtt_ok = mqtt_conectar()

ir_a("menu")
anim_tick_ms   = utime.ticks_ms()
ultimo_tick_ms = utime.ticks_ms()
tiempo_nota_ms = utime.ticks_ms()

# ─────────────────────────────────────────────
#  LOOP PRINCIPAL
# ─────────────────────────────────────────────
while True:
    joy            = leer_joystick()
    btn_id, btn_tp = leer_botones()

    if joy != "none" or btn_id != "none":
        procesar_evento(joy, btn_id, btn_tp)

    actualizar_musica_lofi()
    actualizar_temporizador()
    actualizar_animacion()
    dibujar()

    utime.sleep_ms(POLL_MS)