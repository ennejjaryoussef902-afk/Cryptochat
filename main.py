import os
import sys
import time
import threading
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.clock import Clock
from kivy.utils import platform

# Libreria per la gestione globale dei messaggi senza Ngrok
import paho.mqtt.client as mqtt

# ── 1. GESTIONE FILE SYSTEM (Cartelle protette in android/data/) ──
def inizializza_cartelle():
    if platform == 'android':
        # Trova automaticamente: /sdcard/Android/data/com.cryptochat.app/files/
        from android.storage import app_storage_path
        base_dir = app_storage_path()
        # Per la cartella delle chiamate speciale sulla memoria esterna
        from android.storage import primary_external_storage_path
        calls_base = primary_external_storage_path()
    else:
        base_dir = os.path.join(os.path.expanduser("~"), "CryptoChat")
        calls_base = os.path.expanduser("~")

    # Mappa completa dei percorsi che hai chiesto
    percorsi = {
        "chat": os.path.join(base_dir, "media", "chat"),
        "photos": os.path.join(base_dir, "media", "photos"),
        "videos": os.path.join(base_dir, "media", "videos"),
        "all": os.path.join(base_dir, "media", "all"),
        "calls": os.path.join(calls_base, "Android", "cryptochat", "calls")
    }

    # Crea fisicamente tutte le cartelle all'avvio dell'app
    for nome, path in percorsi.items():
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            
    return percorsi

PATHS = inizializza_cartelle()

# Funzione di smistamento automatico in base all'estensione del file
def smista_file(percorso_file_in_entrata):
    nome_file = os.path.basename(percorso_file_in_entrata)
    estensione = nome_file.split('.')[-1].lowercase()

    if estensione in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
        cartella_destinazione = PATHS["photos"]
    elif estensione in ['mp4', 'mov', 'avi', 'mkv', '3gp']:
        cartella_destinazione = PATHS["videos"]
    elif estensione in ['txt', 'json']:
        cartella_destinazione = PATHS["chat"]
    else:
        cartella_destinazione = PATHS["all"] # .mp3, .wav, .pdf, .zip finiscono tutti qui

    percorso_finale = os.path.join(cartella_destinazione, nome_file)
    os.rename(percorso_file_in_entrata, percorso_finale)
    return percorso_finale

# ── 2. FUNZIONE CRITTOGRAFIA (XOR Simmetrico) ──
def cifra_decifra(messaggio, chiave="StanzaSegreta5B"):
    chiave_ripetuta = (chiave * (len(messaggio) // len(chiave) + 1))[:len(messaggio)]
    return "".join(chr(ord(c) ^ ord(k)) for c, k in zip(messaggio, chiave_ripetuta))


# ── 3. INTERFACCIA GRAFICA (Stile WhatsApp Verde) ──
class WhatsAppChatScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout_principale = BoxLayout(orientation='vertical', background_color=(0.92, 0.90, 0.87, 1))

        # Header Verde Top di WhatsApp
        header = BoxLayout(size_hint_y=0.1, background_color=(0.03, 0.37, 0.33, 1), padding=10, spacing=10)
        info_contatto = BoxLayout(orientation='vertical')
        self.label_nome = Label(text="CryptoChat Amico", font_size=18, bold=True, halign='left')
        self.label_stato = Label(text="Online", font_size=12, text_size=(None, None), color=(0.7, 0.9, 0.8, 1))
        info_contatto.add_widget(self.label_nome)
        info_contatto.add_widget(self.label_stato)
        header.add_widget(info_contatto)

        # Pulsanti Chiamate veloci nell'header
        btn_call = Button(text="📞", size_hint_x=0.15, background_color=(0,0,0,0), font_size=20, on_press=self.click_chiama)
        btn_vcall = Button(text="📹", size_hint_x=0.15, background_color=(0,0,0,0), font_size=20, on_press=self.click_video)
        header.add_widget(btn_call)
        header.add_widget(btn_vcall)
        layout_principale.add_widget(header)

        # Area dei Messaggi (Scrollabile)
        self.scroll = ScrollView(size_hint_y=0.8)
        self.box_messaggi = BoxLayout(orientation='vertical', spacing=8, size_hint_y=None, padding=10)
        self.box_messaggi.bind(texture_size=self.box_messaggi.setter('size'))
        
        self.chat_logs = Label(text="[color=888888]I messaggi in questa stanza sono cifrati.[/color]\n", size_hint_y=None, halign='left', valign='top', markup=True)
        self.chat_logs.bind(texture_size=self.chat_logs.setter('size'))
        self.box_messaggi.add_widget(self.chat_logs)
        self.scroll.add_widget(self.box_messaggi)
        layout_principale.add_widget(self.scroll)

        # Barra di Input Inferiore (Messaggio + Allegati)
        input_bar = BoxLayout(size_hint_y=0.1, padding=5, spacing=5)
        btn_file = Button(text="📎", size_hint_x=0.12, background_color=(0.5, 0.5, 0.5, 1), on_press=self.simula_ricezione_file)
        self.input_testo = TextInput(hint_text="Messaggio", multiline=False)
        btn_invia = Button(text="➤", size_hint_x=0.15, background_color=(0.03, 0.37, 0.33, 1), on_press=self.invia_messaggio)
        
        input_bar.add_widget(btn_file)
        input_bar.add_widget(self.input_testo)
        input_bar.add_widget(btn_invia)
        layout_principale.add_widget(input_bar)

        self.add_widget(layout_principale)

        # Configurazione Client Paho MQTT Globale
        self.topic = "cryptochat/whatsapp/stanza_condivisa"
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        threading.Thread(target=self.connetti_network, daemon=True).start()

    def connetti_network(self):
        try:
            self.client.connect("broker.hivemq.com", 1883, 60)
            self.client.loop_forever()
        except:
            Clock.schedule_once(lambda dt: self.aggiorna_schermo("[Sistema]: Connessione fallita. Riprovo..."))

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.client.subscribe(self.topic)
            Clock.schedule_once(lambda dt: self.aggiorna_schermo("[color=00ff00][Sistema]: Sei Online ✔[/color]"))

    def on_message(self, client, userdata, msg):
        try:
            raw_data = msg.payload.decode('utf-8')
            testo_chiaro = cifra_decifra(raw_data)
            
            # Se il messaggio non è mio, lo stampo aggiungendo la doppia spunta blu di lettura
            if not testo_chiaro.startswith("[Tu]"):
                Clock.schedule_once(lambda dt: self.aggiorna_schermo(f"{testo_chiaro} [color=00aaff]✔✔[/color]"))
        except:
            pass

    def aggiorna_schermo(self, testo):
        self.chat_logs.text += testo + "\n"
        # Salvataggio automatico del log nella cartella chat richiesta
        with open(os.path.join(PATHS["chat"], "chat_history.txt"), "a", encoding="utf-8") as f:
            f.write(testo + "\n")

    def invia_messaggio(self, instance):
        testo = self.input_testo.text.strip()
        if testo:
            msg_pulito = f"[Amico]: {testo}"
            msg_cifrato = cifra_decifra(msg_pulito)
            try:
                self.client.publish(self.topic, msg_cifrato)
                # Mostra sullo schermo il tuo messaggio con una spunta grigia (inviato)
                self.aggiorna_schermo(f"[Tu]: {testo} [color=888888]✔[/color]")
                self.input_testo.text = ""
                
                # Simula l'evoluzione delle spunte (dopo 1 secondo diventa Consegnato ✔✔ grigio)
                Clock.schedule_once(lambda dt: self.aggiorna_spunta_consegna(testo), 1.0)
            except:
                self.aggiorna_schermo("[Sistema]: Errore di rete.")

    def aggiorna_spunta_consegna(self, testo):
        # Sostituisce la spunta singola con la doppia spunta grigia di WhatsApp
        vecchio = f"[Tu]: {testo} [color=888888]✔[/color]"
        nuovo = f"[Tu]: {testo} [color=888888]✔✔[/color]"
        if vecchio in self.chat_logs.text:
            self.chat_logs.text = self.chat_logs.text.replace(vecchio, nuovo)

    # ── 4. FUNZIONALITÀ EXTRA (Rubrica, Chiamate, All Files) ──
    def click_chiama(self, instance):
        self.aggiorna_schermo("[color=00ff00]📞 Chiamata vocale avviata...[/color]")
        # Registra la chiamata nella cartella calls esterna richiesta
        with open(os.path.join(PATHS["calls"], "registro_chiamate.txt"), "a") as f:
            f.write(f"Chiamata effettuata il {time.strftime('%d/%m/%y %H:%M:%S')}\n")

    def click_video(self, instance):
        self.aggiorna_schermo("[color=00ff00]📹 Videochiamata di gruppo avviata...[/color]")
        with open(os.path.join(PATHS["calls"], "registro_chiamate.txt"), "a") as f:
            f.write(f"Videochiamata effettuata il {time.strftime('%d/%m/%y %H:%M:%S')}\n")

    def simula_ricezione_file(self, instance):
        # Esempio pratico di funzionamento dello smistatore automatico
        test_file = os.path.join(PATHS["chat"], "documento.pdf")
        with open(test_file, "w") as f:
            f.write("Finto documento PDF ricevuto")
        
        # Chiama l'algoritmo di smistamento per spost