# ============================================================
#  POMO - Mascota Virtual Pomodoro
#  ESP32 + LCD I2C 20x4 + 2 botones (GPIO14, GPIO12)
#  MicroPython - Thonny
# ============================================================
#
#  CONTROLES:
#    Click corto (<800ms)  UP=subir/+5min  DOWN=bajar/-5min
#    Hold largo (>=800ms)  cualquier boton = ENTRAR o VOLVER
#
#  ESTADOS:
#    menu         -> pantalla principal con selector
#    estudiar_cfg -> elegir minutos (5..60, pasos de 5)
#    estudiar_run -> cuenta regresiva activa
#    descanso_run -> descanso 5 min tras sesion completa
#    vida         -> mostrar vitalidad
#
# ============================================================

from machine import Pin, I2C
from lcd_i2c import LCD
import utime

# ─────────────────────────────────────────────
#  HARDWARE
# ─────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21))
lcd = LCD(39, 20, 4, i2c=i2c)
lcd.begin()

BTN_UP   = Pin(14, Pin.IN, Pin.PULL_UP)
BTN_DOWN = Pin(12, Pin.IN, Pin.PULL_UP)

# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────
HOLD_MS      = 800
DEBOUNCE_MS  = 40
POLL_MS      = 20
DESCANSO_SEG = 5 * 60

OPCIONES = ["Estudiar", "Vitalidad"]

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

# Animaciones (2 frames)
ANIM_IDLE = ["(^-^)/", "(^-^) "]
ANIM_EST  = ["(>_<)/", "(>_<) "]
ANIM_DONE = ["(^o^)/", "(^o^) "]

# ─────────────────────────────────────────────
#  UTILIDADES - sin ljust (MicroPython no lo tiene)
# ─────────────────────────────────────────────
def rpad(s, n):
    """Rellena con espacios a la derecha hasta largo n."""
    while len(s) < n:
        s = s + " "
    return s

def centrar(texto, row, ancho=20):
    pad = (ancho - len(texto)) // 2
    if pad < 0:
        pad = 0
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
    centrar("Hola, soy Pomo!", 0)
    centrar(get_frame(ANIM_IDLE), 1)
    for i in range(2):
        prefijo = "> " if i == seleccion else "  "
        # rpad para limpiar residuos al cambiar seleccion
        linea = rpad(prefijo + OPCIONES[i], 16)
        escribir(2, i + 2, linea)

def dibujar_estudiar_cfg():
    lcd.clear()
    centrar("-- Configurar --", 0)
    centrar("Tiempo:", 1)
    # Formato: "< 25 min >"
    val = str(minutos_cfg)
    tiempo_str = "< " + val + " min >"
    centrar(tiempo_str, 2)
    centrar("[hold] = iniciar", 3)

def dibujar_estudiar_run():
    m = seg_restantes // 60
    s = seg_restantes % 60
    # Formato manual 02d
    ms = ("0" if m < 10 else "") + str(m)
    ss = ("0" if s < 10 else "") + str(s)
    tiempo_str = ms + " : " + ss
    centrar("-- Estudiando --", 0)
    centrar(get_frame(ANIM_EST), 1)
    centrar(tiempo_str, 2)
    centrar("[hold] = cancelar", 3)

def dibujar_descanso_run():
    m = seg_restantes // 60
    s = seg_restantes % 60
    ms = ("0" if m < 10 else "") + str(m)
    ss = ("0" if s < 10 else "") + str(s)
    tiempo_str = ms + " : " + ss
    centrar("-- Descansando --", 0)
    centrar(get_frame(ANIM_DONE), 1)
    centrar(tiempo_str, 2)
    centrar("[hold] = saltar", 3)

def dibujar_vida():
    lcd.clear()
    centrar("-- Vitalidad --", 0)
    # Corazones en ASCII puro: <3 lleno,  .. vacio
    llenos = "<3 " * vida
    vacios = ".. " * (3 - vida)
    corazones = llenos + vacios
    # Quitar espacio final
    corazones = corazones.strip()
    centrar(corazones, 1)
    pct = str(vida * 100 // 3) + "%"
    centrar(pct, 2)
    centrar("[hold] = volver", 3)

def dibujar_sesion_ok():
    lcd.clear()
    centrar("Sesion completa!", 0)
    centrar("(^o^)/", 1)
    centrar("Bien hecho!", 2)
    centrar("Descansando...", 3)

# ─────────────────────────────────────────────
#  LECTURA DE BOTONES
#  Retorna: "none" | "click_up" | "click_down"
#           | "hold_up" | "hold_down"
# ─────────────────────────────────────────────
def leer_boton():
    for btn, nombre in ((BTN_UP, "up"), (BTN_DOWN, "down")):
        if btn.value() == 0:
            utime.sleep_ms(DEBOUNCE_MS)
            if btn.value() != 0:
                continue  # ruido
            t0 = utime.ticks_ms()
            es_hold = False
            while btn.value() == 0:
                if utime.ticks_diff(utime.ticks_ms(), t0) >= HOLD_MS:
                    es_hold = True
                    break
                utime.sleep_ms(POLL_MS)
            # Esperar release siempre
            while btn.value() == 0:
                utime.sleep_ms(POLL_MS)
            utime.sleep_ms(80)  # pausa post-evento
            if es_hold:
                return "hold_" + nombre
            else:
                return "click_" + nombre
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

def procesar_evento(ev):
    global seleccion, minutos_cfg, vida

    if estado == "menu":
        if ev == "click_up":
            seleccion = (seleccion - 1) % len(OPCIONES)
            ir_a("menu")
        elif ev == "click_down":
            seleccion = (seleccion + 1) % len(OPCIONES)
            ir_a("menu")
        elif ev in ("hold_up", "hold_down"):
            if seleccion == 0:
                ir_a("estudiar_cfg")
            else:
                ir_a("vida")

    elif estado == "estudiar_cfg":
        if ev == "click_up":
            minutos_cfg = minutos_cfg + 5
            if minutos_cfg > 60:
                minutos_cfg = 60
            ir_a("estudiar_cfg")
        elif ev == "click_down":
            minutos_cfg = minutos_cfg - 5
            if minutos_cfg < 5:
                minutos_cfg = 5
            ir_a("estudiar_cfg")
        elif ev in ("hold_up", "hold_down"):
            ir_a("estudiar_run")     # ENTRAR -> iniciar sesion
        # No hay "volver" desde cfg; hold inicia.
        # Para volver al menu sin iniciar: doble hold no es necesario
        # porque el usuario puede subir/bajar y luego hold para iniciar.
        # Si se quiere cancelar cfg sin iniciar: mantener DOWN cuando
        # minutos ya esta en el valor deseado lanza la sesion igual,
        # que es el comportamiento mas simple con 2 botones.

    elif estado == "estudiar_run":
        if ev in ("hold_up", "hold_down"):
            vida = vida - 1
            if vida < 0:
                vida = 0
            ir_a("menu")             # VOLVER -> cancelar sesion

    elif estado == "descanso_run":
        if ev in ("hold_up", "hold_down"):
            ir_a("menu")             # VOLVER -> saltar descanso

    elif estado == "vida":
        if ev in ("hold_up", "hold_down"):
            ir_a("menu")             # VOLVER -> menu principal

# ─────────────────────────────────────────────
#  TEMPORIZADOR
# ─────────────────────────────────────────────
def actualizar_temporizador():
    global seg_restantes, ultimo_tick_ms, necesita_dibujar, vida

    if estado not in ("estudiar_run", "descanso_run"):
        return

    ahora = utime.ticks_ms()
    if utime.ticks_diff(ahora, ultimo_tick_ms) >= 1000:
        ultimo_tick_ms = ahora
        seg_restantes  = seg_restantes - 1
        necesita_dibujar = True

        if seg_restantes <= 0:
            if estado == "estudiar_run":
                vida = vida + 1
                if vida > 3:
                    vida = 3
                dibujar_sesion_ok()
                utime.sleep_ms(2500)
                ir_a("descanso_run")
            else:
                ir_a("menu")

# ─────────────────────────────────────────────
#  ANIMACION
# ─────────────────────────────────────────────
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
#  DIBUJO PRINCIPAL
# ─────────────────────────────────────────────
def dibujar():
    global necesita_dibujar
    if not necesita_dibujar:
        return
    necesita_dibujar = False

    if   estado == "menu":
        dibujar_menu()
    elif estado == "estudiar_cfg":
        dibujar_estudiar_cfg()
    elif estado == "estudiar_run":
        dibujar_estudiar_run()
    elif estado == "descanso_run":
        dibujar_descanso_run()
    elif estado == "vida":
        dibujar_vida()

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

# ─────────────────────────────────────────────
#  LOOP PRINCIPAL
# ─────────────────────────────────────────────
while True:
    ev = leer_boton()
    if ev != "none":
        procesar_evento(ev)
    actualizar_temporizador()
    actualizar_animacion()
    dibujar()
    utime.sleep_ms(POLL_MS)
