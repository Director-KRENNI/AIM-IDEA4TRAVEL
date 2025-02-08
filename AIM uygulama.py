import sys
import os
import serial
import serial.tools.list_ports
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QLabel, 
                            QVBoxLayout, QWidget, QComboBox, QTextEdit,
                            QDialog, QLineEdit, QHBoxLayout, QMessageBox)
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread

# Başlangıç havalimanı ve COM port eşleşmeleri
ucak_com_portlari = {
    "IST -> VCE (13.00)": "COM3",
    "IST -> AAL (17.00)": "COM4",
    "IST -> AMS (13.30)": "COM5",
    "IST -> BCN (11.00)": "COM6",
    "IST -> AYT (16.00)": "COM7",
    "IST -> BML (12.00)": "COM8",
    "IST -> BLQ (22.00)": "COM9",
    "IST -> AEP (19.15)": "COM10",
    "IST -> CHI (15.30)": "COM11",
    "IST -> SDY (05.45)": "COM12"
}

# Veri yapıları
ucak_bagajlari = {ucak: set() for ucak in ucak_com_portlari}
rfid_to_ucak = {}

def send_email(to_email, subject, body):
    from_email = "your_email@example.com"
    from_password = "your_email_password"

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.example.com', 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        print("E-posta başarıyla gönderildi")
    except Exception as e:
        print(f"E-posta gönderilemedi: {str(e)}")

class YeniUcakDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yeni Uçak Ekle")
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout()
        
        self.havalimani_input = QLineEdit()
        self.havalimani_input.setPlaceholderText("Havalimanı Adı (Örn: Sabiha Gökçen Havalimanı)")
        self.com_port_input = QLineEdit()
        self.com_port_input.setPlaceholderText("COM Port (Örn: COM13)")
        
        self.kaydet_btn = QPushButton("Kaydet")
        self.kaydet_btn.clicked.connect(self.validate_inputs)
        
        layout.addWidget(QLabel("Havalimanı Adı:"))
        layout.addWidget(self.havalimani_input)
        layout.addWidget(QLabel("COM Port:"))
        layout.addWidget(self.com_port_input)
        layout.addWidget(self.kaydet_btn)
        
        self.setLayout(layout)

    def validate_inputs(self):
        havalimani = self.havalimani_input.text().strip()
        com_port = self.com_port_input.text().strip().upper()
        
        if not havalimani or not com_port:
            QMessageBox.warning(self, "Uyarı", "Lütfen tüm alanları doldurun!")
            return
            
        if havalimani in ucak_com_portlari:
            QMessageBox.warning(self, "Uyarı", "Bu havalimanı zaten kayıtlı!")
            return
            
        if com_port in ucak_com_portlari.values():
            QMessageBox.warning(self, "Uyarı", "Bu COM portu zaten kullanımda!")
            return
            
        self.accept()

class SerialWorker(QObject):
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connection_status = pyqtSignal(bool)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.ser = None
        self.running = False

    @pyqtSlot()
    def start_reading(self):
        self.running = True
        try:
            available_ports = [p.device for p in serial.tools.list_ports.comports()]
            if self.port not in available_ports:
                raise serial.SerialException(f"Port {self.port} not found!")

            self.ser = serial.Serial(
                self.port,
                baudrate=115200,
                timeout=0.1
            )
            self.connection_status.emit(True)
            
            while self.running:
                if self.ser.in_waiting:
                    data = self.ser.readline().decode().strip()
                    if data:
                        self.data_received.emit(data)
        except Exception as e:
            self.error_occurred.emit(f"❌ PORT HATASI: {self.port} bulunamadı veya erişilemiyor!\nDetay: {str(e)}")
            self.connection_status.emit(False)
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()

    @pyqtSlot()
    def stop_reading(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

class RFIDApp(QMainWindow):
    ucak_listesi_guncellendi = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.current_worker = None
        self.current_thread = None
        self.okunan_bagajlar = set()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("RFID Bagaj Takip Sistemi")
        self.setGeometry(200, 200, 700, 600)

        main_layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        
        self.yeni_ucak_btn = QPushButton("Yeni Uçak Ekle")
        self.yeni_ucak_btn.clicked.connect(self.yeni_ucak_ekle)
        self.sil_ucak_btn = QPushButton("Uçak Sil")
        self.sil_ucak_btn.clicked.connect(self.ucak_sil)
        
        top_layout.addWidget(self.yeni_ucak_btn)
        top_layout.addWidget(self.sil_ucak_btn)
        
        self.ucak_secim = QComboBox()
        self.ucak_secim.addItems(ucak_com_portlari.keys())
        
        self.baslat_buton = QPushButton("Bağlan ve RFID Oku")
        self.baslat_buton.clicked.connect(self.toggle_connection)
        
        self.bagaj_giris = QTextEdit()
        self.bagaj_giris.setPlaceholderText("Her satıra bir RFID kodu girin")
        
        self.kaydet_buton = QPushButton("Bagaj RFID Kaydet")
        self.kaydet_buton.clicked.connect(self.bagaj_kaydet)
        
        self.kontrol_buton = QPushButton("Uçağı Kontrol Et")
        self.kontrol_buton.clicked.connect(self.ucagi_kontrol_et)
        
        self.cikti_alanı = QTextEdit()
        self.cikti_alanı.setReadOnly(True)
        
        main_layout.addLayout(top_layout)
        main_layout.addWidget(QLabel("Uçak Seçin:"))
        main_layout.addWidget(self.ucak_secim)
        main_layout.addWidget(self.baslat_buton)
        main_layout.addWidget(QLabel("RFID Kodları:"))
        main_layout.addWidget(self.bagaj_giris)
        main_layout.addWidget(self.kaydet_buton)
        main_layout.addWidget(self.kontrol_buton)
        main_layout.addWidget(QLabel("Sistem Çıktısı:"))
        main_layout.addWidget(self.cikti_alanı)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.ucak_listesi_guncellendi.connect(self.guncel_ucak_listesi)

    def yeni_ucak_ekle(self):
        dialog = YeniUcakDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            yeni_havalimani = dialog.havalimani_input.text().strip()
            yeni_com_port = dialog.com_port_input.text().strip().upper()
            
            ucak_com_portlari[yeni_havalimani] = yeni_com_port
            ucak_bagajlari[yeni_havalimani] = set()
            
            self.ucak_listesi_guncellendi.emit()
            self.cikti_alanı.append(f"✈️ Yeni uçak eklendi: {yeni_havalimani} ({yeni_com_port})")

    def ucak_sil(self):
        secili_ucak = self.ucak_secim.currentText()
        
        if secili_ucak in ucak_com_portlari:
            # Uçağın bagaj verilerini ve COM portunu temizle
            del ucak_com_portlari[secili_ucak]
            del ucak_bagajlari[secili_ucak]
            
            # Eğer RFID uçağa bağlıysa, sil
            rfid_to_remove = [rfid for rfid, ucm in rfid_to_ucak.items() if ucm == secili_ucak]
            for rfid in rfid_to_remove:
                del rfid_to_ucak[rfid]
            
            self.ucak_listesi_guncellendi.emit()
            self.cikti_alanı.append(f"🛑 {secili_ucak} silindi!")
        else:
            self.cikti_alanı.append("❌ Silinecek uçak bulunamadı!")

    def guncel_ucak_listesi(self):
        self.ucak_secim.clear()
        self.ucak_secim.addItems(ucak_com_portlari.keys())

    def toggle_connection(self):
        if self.current_worker and self.current_worker.running:
            self.disconnect_serial()  # Mevcut bağlantıyı kes
        else:
            self.connect_serial()  # Yeni bağlantıyı başlat

    def connect_serial(self):
        selected_ucak = self.ucak_secim.currentText()
        com_port = ucak_com_portlari.get(selected_ucak)
        
        if not com_port:
            self.cikti_alanı.append("❌ Geçersiz COM port!")
            return

        # Yeni bir QThread ve SerialWorker başlat
        self.current_thread = QThread()
        self.current_worker = SerialWorker(com_port)
        self.current_worker.moveToThread(self.current_thread)
        
        # Worker ile bağlantı sağlanacak sinyalleri bağla
        self.current_worker.connection_status.connect(self.handle_connection_status)
        self.current_worker.data_received.connect(self.handle_rfid)
        self.current_worker.error_occurred.connect(self.handle_error)
        
        # Thread başladığında worker'ın start_reading metodunu çağır
        self.current_thread.started.connect(self.current_worker.start_reading)
        self.current_thread.finished.connect(self.cleanup_connection)
        
        # Yeni bağlantıyı başlat
        self.current_thread.start()

    def handle_connection_status(self, status):
        selected_ucak = self.ucak_secim.currentText()
        com_port = ucak_com_portlari.get(selected_ucak)
        
        if status:
            self.baslat_buton.setText("Bağlantıyı Kes")
            self.cikti_alanı.append(f"✅ BAĞLANTI BAŞARILI: {selected_ucak} ({com_port})")
        else:
            self.baslat_buton.setText("Bağlan ve RFID Oku")
            self.cikti_alanı.append(f"❌ BAĞLANTI BAŞARISIZ: {selected_ucak} ({com_port})")

    def disconnect_serial(self):
        # Eğer worker varsa, durdur ve bağlantıyı sonlandır
        if self.current_worker:
            self.current_worker.stop_reading()  # Worker'ı durdur
            self.current_thread.quit()  # Thread'i sonlandır
            self.current_thread.wait()  # Thread'in tamamlanmasını bekle

        # Mevcut bağlantı sonlandırıldığında UI'de buna göre işlem yap
        self.baslat_buton.setText("Bağlan ve RFID Oku")
        self.cikti_alanı.append("🔌 Bağlantı kesildi")

    def cleanup_connection(self):
        self.current_worker = None
        self.current_thread = None

    def handle_rfid(self, rfid):
        self.cikti_alanı.append(f"📡 Okunan RFID: {rfid}")
        self.okunan_bagajlar.add(rfid)
        self.bagaj_kontrol(rfid)

    def handle_error(self, message):
        self.cikti_alanı.append(message)

    def bagaj_kontrol(self, rfid):
        current_ucak = self.ucak_secim.currentText()
        if rfid in rfid_to_ucak:
            if rfid_to_ucak[rfid] == current_ucak:
                self.cikti_alanı.append(f"✅ Tanındı: {rfid} (Bu uçak)")
                # E-posta gönder
                to_email = "bavul_sahibi@example.com"
                subject = "Bavulunuz Doğru Uçakta Okundu"
                body = f"Sayın yolcu, bavulunuz {rfid} doğru uçakta ({current_ucak}) başarıyla okundu."
                send_email(to_email, subject, body)
            else:
                self.cikti_alanı.append(f"⚠️ Uyarı: {rfid} ({rfid_to_ucak[rfid]} uçağına ait)")
        else:
            self.cikti_alanı.append(f"🚨 Tanınmayan bagaj! RFID: {rfid}")

    def bagaj_kaydet(self):
        current_ucak = self.ucak_secim.currentText()
        
        if current_ucak not in ucak_com_portlari:
            self.cikti_alanı.append("❌ Geçersiz uçak seçimi!")
            return

        rfid_list = self.bagaj_giris.toPlainText().split()
        
        if not rfid_list:
            self.cikti_alanı.append("❌ Kaydedilecek RFID bulunamadı!")
            return

        for rfid in rfid_list:
            rfid = rfid.strip()
            if rfid:
                if rfid in rfid_to_ucak:
                    self.cikti_alanı.append(f"⚠️ UYARI: {rfid} zaten {rfid_to_ucak[rfid]} uçağına kayıtlı")
                else:
                    ucak_bagajlari[current_ucak].add(rfid)
                    self.okunan_bagajlar.discard(rfid)  # Yeniden sayacı başlat
                    rfid_to_ucak[rfid] = current_ucak
                    self.cikti_alanı.append(f"✓ KAYIT BAŞARILI: {rfid} → {current_ucak}")
        
        self.bagaj_giris.clear()
    
    def ucagi_kontrol_et(self):
        current_ucak = self.ucak_secim.currentText()
        kayitli_bagajlar = ucak_bagajlari.get(current_ucak, set())
        eksik_bagajlar = kayitli_bagajlar - self.okunan_bagajlar

        if eksik_bagajlar:
            self.cikti_alanı.append(f"⚠️ Eksik Valizler: {', '.join(eksik_bagajlar)}")
        else:
            self.cikti_alanı.append("✅ Tüm valizler yerlerinde!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RFIDApp()
    window.show()
    sys.exit(app.exec())