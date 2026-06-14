from machine import Pin, PWM, unique_id
import ubinascii
import time

# Identificadores del sistema
POMO_ID = "POMO001"
DEVICE_ID = "cofre-" + ubinascii.hexlify(unique_id()).decode()

print("POMO_ID:", POMO_ID)
print("DEVICE_ID:", DEVICE_ID)

# Pines en el ESP32
MICROSWITCH_PIN = 14
SERVO_PIN = 18

# Con PULL_UP:
# libre = 1
# presionado = 0
microswitch = Pin(MICROSWITCH_PIN, Pin.IN, Pin.PULL_UP)

servo = PWM(Pin(SERVO_PIN), freq=50)

# Parámetros preliminares del pestillo
ANGULO_ABIERTO = 20
ANGULO_CERRADO = 120
TIEMPO_ESPERA = 10

bloqueado = False


def mover_servo(angulo):
    duty = int(25 + (angulo * 100 / 180))
    servo.duty(duty)
    time.sleep(0.4)


def celular_detectado():
    return microswitch.value() == 0


def abrir_cofre(motivo):
    global bloqueado
    mover_servo(ANGULO_ABIERTO)
    bloqueado = False
    print("COFRE ABIERTO:", motivo)


def cerrar_cofre():
    global bloqueado
    mover_servo(ANGULO_CERRADO)
    bloqueado = True
    print("COFRE BLOQUEADO")


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