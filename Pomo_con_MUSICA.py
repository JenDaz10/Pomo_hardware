# ============================================================
#  POMO - Mascota Virtual Pomodoro
#  ESP32 + LCD I2C 20x4 + Joystick + Botones + Buzzer + RTC
# ============================================================

from machine import Pin, I2C, ADC, PWM
from lcd_i2c import LCD
import utime

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

# Buzzer en Pin 26
buzzer = PWM(Pin(26))
buzzer.duty(0) # Iniciar en silencio

# Dirección I2C estándar para RTCs (DS1307 o DS3231)
RTC_ADDR = 0x68 

# ─────────────────────────────────────────────
#  CONSTANTES Y NOTAS MUSICALES
# ─────────────────────────────────────────────
DEBOUNCE_MS  = 40
POLL_MS      = 20
DESCANSO_SEG = 5 * 60
JOY_REPEAT_MS = 300

OPCIONES = ["Estudiar", "Vitalidad"]

# Frecuencias de notas musicales (Hz)
C4 = 261; D4 = 293; E4 = 329; F4 = 349; G4 = 392; A4 = 440; B4 = 493; C5 = 523

# Formato: (Frecuencia, Duración en ms). Frecuencia 0 = Silencio
MELODIA_TRIUNFO = [(C4, 150), (E4, 150), (G4, 150), (C5, 400), (0, 100)]
MELODIA_TRISTE  = [(G4, 300), (F4, 300), (E4, 300), (D4, 600), (0, 100)]
MELODIA_MENU    = [(C4, 400), (E4, 400), (G4, 400), (E4, 400), (0, 800)] # Bucle suave

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

# Variables para música no bloqueante del menú
nota_menu_idx = 0
tiempo_nota_ms = 0

ANIM_IDLE = ["(^-^)/", "(^-^) "]
ANIM_EST  = ["(>_<)/", "(>_<) "]
ANIM_DONE = ["(^o^)/", "(^o^) "]

# ─────────────────────────────────────────────
#  UTILIDADES DE AUDIO Y HORA
# ─────────────────────────────────────────────
def reproducir_melodia_bloqueante(melodia):
    buzzer.duty(512) # Volumen medio (rango 0-1023)
    for frec, duracion in melodia:
        if frec == 0:
            buzzer.duty(0)
        else:
            buzzer.duty(512)
            buzzer.freq(frec)
        utime.sleep_ms(duracion)
    buzzer.duty(0)

def actualizar_musica_menu():
    global nota_menu_idx, tiempo_nota_ms
    
    if estado != "menu":
        buzzer.duty(0) # Asegurar silencio si salimos del menú
        return

    ahora = utime.ticks_ms()
    duracion_actual = MELODIA_MENU[nota_menu_idx][1]
    
    if utime.ticks_diff(ahora, tiempo_nota_ms) >= duracion_actual:
        tiempo_nota_ms = ahora
        nota_menu_idx = (nota_menu_idx + 1) % len(MELODIA_MENU)
        
        frec = MELODIA_MENU[nota_menu_idx][0]
        if frec == 0:
            buzzer.duty(0)
        else:
            buzzer.duty(512)
            buzzer.freq(frec)

def leer_hora_rtc():
    try:
        # Pide 3 bytes desde el registro 0x00 (segundos, minutos, horas)
        i2c.writeto(RTC_ADDR, b'\x00')
        data = i2c.readfrom(RTC_ADDR, 3)
        # Convertir de BCD (Binary-Coded Decimal) a Decimal
        ss = (data[0] & 0x0F) + ((data[0] >> 4) * 10)
        mm = (data[1] & 0x0F) + ((data[1] >> 4) * 10)
        hh = (data[2] & 0x0F) + (((data[2] & 0x30) >> 4) * 10)
        return "{:02d}:{:02d}:{:02d}".format(hh, mm, ss)
    except:
        return "--:--:--"

# ─────────────────────────────────────────────
#  UTILIDADES DE PANTALLA
# ─────────────────────────────────────────────
def rpad(s, n):
    while len(s) < n: s = s + " "
    return s

def centrar(texto, row, ancho=20):
    pad = max((ancho - len(texto)) // 2, 0)
    lcd.set_cursor(pad, row)
    lcd.print(texto)

def escribir(col, row, texto):
    lcd.set_cursor(col, row)
    lcd.print(texto)

def get_frame(anim):
    return anim[frame_idx]

# ─────────────────────────────────────────────
#  PANTALLAS
# ─────────────────────────────────────────────
def dibujar_menu():
    lcd.clear()
    hora = leer_hora_rtc()
    escribir(0, 0, "Pomo        " + hora) # Muestra nombre y hora
    centrar(get_frame(ANIM_IDLE), 1)
    for i in range(2):
        prefijo = "> " if i == seleccion else "  "
        linea = rpad(prefijo + OPCIONES[i], 16)
        escribir(2, i + 2, linea)

def dibujar_estudiar_cfg():
    lcd.clear()
    centrar("-- Configurar --", 0)
    centrar("Tiempo:", 1)
    tiempo_str = "< " + str(minutos_cfg) + " min >"
    centrar(tiempo_str, 2)
    centrar("[OK] = iniciar", 3)

def dibujar_estudiar_run():
    m, s = divmod(seg_restantes, 60)
    ms = "{:02d}".format(m)
    ss = "{:02d}".format(s)
    lcd.clear()
    centrar("-- Estudiando --", 0)
    centrar(get_frame(ANIM_EST), 1)
    centrar(ms + " : " + ss, 2)
    centrar("[BACK] = cancelar", 3)

def dibujar_descanso_run():
    m, s = divmod(seg_restantes, 60)
    ms = "{:02d}".format(m)
    ss = "{:02d}".format(s)
    lcd.clear()
    centrar("-- Descansando --", 0)
    centrar(get_frame(ANIM_DONE), 1)
    centrar(ms + " : " + ss, 2)
    centrar("[BACK] = saltar", 3)

def dibujar_vida():
    lcd.clear()
    centrar("-- Vitalidad --", 0)
    llenos = "<3 " * vida
    vacios = ".. " * (3 - vida)
    centrar((llenos + vacios).strip(), 1)
    centrar(str(vida * 100 // 3) + "%", 2)
    centrar("[BACK] = volver", 3)

def dibujar_sesion_ok():
    lcd.clear()
    centrar("Sesion completa!", 0)
    centrar("(^o^)/", 1)
    centrar("Bien hecho!", 2)
    centrar("Descansando...", 3)

# ─────────────────────────────────────────────
#  LECTURA JOYSTICK Y BOTONES
# ─────────────────────────────────────────────
def leer_joystick():
    global ultimo_joy_ms
    xv, yv = joy_x.read(), joy_y.read()
    direccion = "none"

    if yv < 500: direccion = "arriba"
    elif yv > 3500: direccion = "abajo"
    elif xv < 500: direccion = "derecha"
    elif xv > 3500: direccion = "izquierda"

    if direccion == "none":
        ultimo_joy_ms = 0
        return "none"

    ahora = utime.ticks_ms()
    if ultimo_joy_ms == 0 or utime.ticks_diff(ahora, ultimo_joy_ms) >= JOY_REPEAT_MS:
        ultimo_joy_ms = ahora
        return direccion
    return "none"

def leer_boton():
    for btn, nombre in ((BTN_OK, "ok"), (BTN_BACK, "back")):
        if btn.value() == 0:
            utime.sleep_ms(DEBOUNCE_MS)
            if btn.value() != 0: continue
            while btn.value() == 0: utime.sleep_ms(POLL_MS)
            utime.sleep_ms(80)
            return nombre
    return "none"

# ─────────────────────────────────────────────
#  MAQUINA DE ESTADOS
# ─────────────────────────────────────────────
def ir_a(nuevo):
    global estado, necesita_dibujar, seg_restantes, ultimo_tick_ms
    estado = nuevo
    necesita_dibujar = True
    if nuevo == "estudiar_run":
        seg_restantes  = minutos_cfg * 60
        ultimo_tick_ms = utime.ticks_ms()
    elif nuevo == "descanso_run":
        seg_restantes  = DESCANSO_SEG
        ultimo_tick_ms = utime.ticks_ms()

def procesar_evento(joy, btn):
    global seleccion, minutos_cfg, vida

    if estado == "menu":
        if joy == "arriba":
            seleccion = (seleccion - 1) % len(OPCIONES)
            ir_a("menu")
        elif joy == "abajo":
            seleccion = (seleccion + 1) % len(OPCIONES)
            ir_a("menu")
        elif btn == "ok":
            ir_a("estudiar_cfg" if seleccion == 0 else "vida")

    elif estado == "estudiar_cfg":
        if joy == "derecha":
            minutos_cfg = min(minutos_cfg + 5, 60)
            ir_a("estudiar_cfg")
        elif joy == "izquierda":
            minutos_cfg = max(minutos_cfg - 5, 5)
            ir_a("estudiar_cfg")
        elif btn == "ok":
            ir_a("estudiar_run")
        elif btn == "back":
            ir_a("menu")

    elif estado == "estudiar_run":
        if btn == "back":
            # CANCELADO: Pierde vida y suena triste
            vida = max(vida - 1, 0)
            buzzer.duty(0) # Apaga música actual si la hubiera
            reproducir_melodia_bloqueante(MELODIA_TRISTE)
            ir_a("menu")

    elif estado in ("descanso_run", "vida"):
        if btn == "back":
            ir_a("menu")

# ─────────────────────────────────────────────
#  TEMPORIZADORES Y ANIMACION
# ─────────────────────────────────────────────
def actualizar_temporizador():
    global seg_restantes, ultimo_tick_ms, necesita_dibujar, vida

    # Forzar actualización del reloj en el menú cada segundo
    ahora = utime.ticks_ms()
    if estado == "menu":
        if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
            ultimo_tick_ms = ahora
            necesita_dibujar = True
        return

    if estado not in ("estudiar_run", "descanso_run"):
        return

    if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
        ultimo_tick_ms = ahora
        seg_restantes -= 1
        necesita_dibujar = True

        if seg_restantes <= 0:
            if estado == "estudiar_run":
                # ÉXITO: Gana vida y suena victoria
                vida = min(vida + 1, 3)
                dibujar_sesion_ok()
                reproducir_melodia_bloqueante(MELODIA_TRIUNFO)
                ir_a("descanso_run")
            else:
                ir_a("menu")

def actualizar_animacion():
    global frame_idx, anim_tick_ms, necesita_dibujar
    intervalo = 600 if estado == "menu" else 400
    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, anim_tick_ms) >= intervalo:
        anim_tick_ms = ahora
        frame_idx = 1 - frame_idx
        if estado in ("menu", "estudiar_run", "descanso_run"):
            necesita_dibujar = True

# ─────────────────────────────────────────────
#  DIBUJO
# ─────────────────────────────────────────────
def dibujar():
    global necesita_dibujar
    if not necesita_dibujar: return
    necesita_dibujar = False

    if   estado == "menu":         dibujar_menu()
    elif estado == "estudiar_cfg": dibujar_estudiar_cfg()
    elif estado == "estudiar_run": dibujar_estudiar_run()
    elif estado == "descanso_run": dibujar_descanso_run()
    elif estado == "vida":         dibujar_vida()

# ─────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────
lcd.clear()
centrar("Hola! Soy Pomo!", 0)
centrar("(^o^)/", 1)
centrar("Tu comp. de estudio", 2)
centrar("Cargando...", 3)
utime.sleep_ms(2000)

ir_a("menu")
anim_tick_ms   = utime.ticks_ms()
ultimo_tick_ms = utime.ticks_ms()
tiempo_nota_ms = utime.ticks_ms()

# ─────────────────────────────────────────────
#  LOOP PRINCIPAL
# ─────────────────────────────────────────────
while True:
    joy = leer_joystick()
    btn = leer_boton()
    
    if joy != "none" or btn != "none":
        procesar_evento(joy, btn)
        
    actualizar_musica_menu()
    actualizar_temporizador()
    actualizar_animacion()
    dibujar()
    utime.sleep_ms(POLL_MS)