import os
import time

# Check if running on Raspberry Pi
ON_PI = False
try:
    import RPi.GPIO as GPIO
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306, sh1106
    from luma.core.render import canvas
    from PIL import ImageFont
    ON_PI = True
    print("[DeviceController] Hardware libraries loaded. Running on Raspberry Pi.")
except ImportError as e:
    print(f"[DeviceController] Hardware import failed: {e}")
    print("[DeviceController] Running in SIMULATION MODE. (To run on real hardware, install RPi.GPIO and luma.oled)")

class DeviceController:
    def __init__(self, websocket_callback=None):
        self.websocket_callback = websocket_callback
        self.is_locked = True
        self.servo_pin = 18
        self.ir_pin = 17
        self.pwm = None
        self.oled_device = None
        self.font = None
        
        # Load system truetype font if available
        if ON_PI:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
            ]
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        self.font = ImageFont.truetype(path, 11)
                        break
                    except Exception:
                        pass
        if self.font is None:
            try:
                self.font = ImageFont.load_default()
            except Exception:
                self.font = None
        
        self.init_hardware()

    def init_hardware(self):
        if ON_PI:
            try:
                # Initialize GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                
                # Setup IR Sensor Pin
                GPIO.setup(self.ir_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                
                # Setup Servo Pin
                GPIO.setup(self.servo_pin, GPIO.OUT)
                self.pwm = GPIO.PWM(self.servo_pin, 50) # 50Hz frequency
                self.pwm.start(2.5) # 0 degrees (locked)
                
                # Initialize OLED Display
                serial_bus = i2c(port=1, address=0x3C)
                driver_type = os.getenv("OLED_DRIVER", "ssd1306").lower()
                if driver_type == "sh1106":
                    self.oled_device = sh1106(serial_bus)
                    print("[DeviceController] Initialized SH1106 OLED display driver.")
                else:
                    self.oled_device = ssd1306(serial_bus)
                    print("[DeviceController] Initialized SSD1306 OLED display driver.")
                self.display_oled("SYSTEM INITIALIZED", "READY")
            except Exception as e:
                print(f"[DeviceController] Error initializing physical hardware: {e}")
        else:
            print("[DeviceController] [SIM] Hardware Initialized: OLED (GPIO2/3), IR (GPIO17), Servo (GPIO18)")
            self.display_oled("SYSTEM INITIALIZED", "READY")

    def set_lock_state(self, is_locked):
        self.is_locked = is_locked
        angle = 0 if is_locked else 90
        
        if ON_PI and self.pwm:
            try:
                # Calculate duty cycle for SG90 servo
                # 0 degrees = 2.5% duty cycle, 90 degrees = 7.5% duty cycle
                duty_cycle = 2.5 if is_locked else 7.5
                self.pwm.ChangeDutyCycle(duty_cycle)
                time.sleep(0.5) # Allow servo to move
                # Stop sending signal to prevent jittering
                GPIO.output(self.servo_pin, False)
            except Exception as e:
                print(f"[DeviceController] Error moving servo: {e}")
        else:
            print(f"[DeviceController] [SIM] Servo rotated to {angle}° - Door {'LOCKED' if is_locked else 'UNLOCKED'}")
            
        # Update OLED text
        self.display_oled("SYSTEM LOCKED" if is_locked else "DOOR UNLOCKED", "READY" if is_locked else "WELCOME")

    def display_oled(self, line1, line2=""):
        if ON_PI and self.oled_device:
            try:
                with canvas(self.oled_device) as draw:
                    draw.rectangle(self.oled_device.bounding_box, outline="white", fill="black")
                    draw.text((10, 15), line1, fill="white", font=self.font)
                    draw.text((10, 35), line2, fill="white", font=self.font)
            except Exception as e:
                print(f"[DeviceController] Error writing to OLED: {e}")
        else:
            print(f"[DeviceController] [SIM OLED] Screen Display:")
            print(f"  +------------------------------+")
            print(f"  | {line1.center(28)} |")
            print(f"  | {line2.center(28)} |")
            print(f"  +------------------------------+")

        # Notify React frontend simulator of the OLED update
        if self.websocket_callback:
            text = f"{line1}\n{line2}"
            self.websocket_callback(text)

    def set_display_power(self, power_on):
        if ON_PI and self.oled_device:
            try:
                if power_on:
                    self.oled_device.show()
                else:
                    self.oled_device.hide()
            except Exception as e:
                print(f"[DeviceController] Error setting display power: {e}")
        else:
            print(f"[DeviceController] [SIM OLED] Power set to {'ON' if power_on else 'OFF'}")

    def read_ir_sensor(self):
        if ON_PI:
            try:
                # Active low sensor: returns 0 when visitor is detected, 1 when clear
                return GPIO.input(self.ir_pin) == 0
            except Exception as e:
                print(f"[DeviceController] Error reading IR pin: {e}")
                return False
        return False

    def cleanup(self):
        if ON_PI:
            try:
                if self.pwm:
                    self.pwm.stop()
                GPIO.cleanup()
                print("[DeviceController] GPIO cleaned up.")
            except Exception as e:
                print(f"[DeviceController] Error during cleanup: {e}")
