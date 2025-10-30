#!/usr/bin/env python3
"""
SL Trafikläge Monitor - Förenklad version
Bevakar linje 29 (Näsbyparkslinjen) via webbscraping
"""

import requests
import json
import os
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

# Konfiguration
LINE_TO_MONITOR = "29"
LINE_NAME = "Näsbyparkslinjen"
STATE_FILE = Path(__file__).parent / "sl_state.json"
LOG_FILE = Path(__file__).parent / "sl_monitor.log"

class SLMonitorSimple:
    def __init__(self):
        # Vi använder SL:s publika API som inte kräver nyckel
        self.api_url = "https://api.sl.se/api2/trafficsituation.json"
        # Backup: Trafiklab's öppna endpoint
        self.backup_url = "https://api.resrobot.se/v2.1/departureBoard"
        self.api_key = os.environ.get("SL_API_KEY", "")
    
    def log(self, message):
        """Logga meddelanden till fil och konsol"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_message + "\n")
    
    def fetch_disruptions(self):
        """Hämta trafikstörningar från SL"""
        try:
            # Försök med API-nyckeln om den finns
            if self.api_key:
                params = {"key": self.api_key}
                response = requests.get(self.api_url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("StatusCode") == 0:
                        return data
                    else:
                        self.log(f"API returnerade StatusCode: {data.get('StatusCode')}")
            
            # Fallback: Försök utan nyckel (vissa endpoints är öppna)
            self.log("Försöker hämta data utan API-nyckel...")
            response = requests.get(
                "https://api.sl.se/api2/trafficsituation.json",
                timeout=10,
                headers={"User-Agent": "SL-Monitor/1.0"}
            )
            
            if response.status_code == 200:
                data = response.json()
                return data
            
            # Om allt annat misslyckas, använd scraping som backup
            self.log("Standard API fungerade inte, använder alternativ metod...")
            return self.scrape_sl_website()
            
        except Exception as e:
            self.log(f"❌ Fel vid hämtning: {e}")
            return None
    
    def scrape_sl_website(self):
        """Backup-metod: Scrapa SL:s hemsida direkt"""
        try:
            url = "https://sl.se/reseplanering/trafiklaget"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Försök hitta JSON-data i sidan
                content = response.text
                
                # Kolla om linje 29 eller Näsbyparkslinjen nämns
                mentions_29 = "29" in content or "Näsbyparkslinjen" in content.lower()
                has_disruption = "störning" in content.lower() or "förseningar" in content.lower()
                
                if mentions_29 and has_disruption:
                    # Försök extrahera relevant text
                    # Detta är en förenklad version - en riktigt lösning skulle använda BeautifulSoup
                    return {
                        "has_disruption": True,
                        "source": "website_scraping"
                    }
                else:
                    return {
                        "has_disruption": False,
                        "source": "website_scraping"
                    }
            
        except Exception as e:
            self.log(f"⚠️  Scraping misslyckades: {e}")
        
        return None
    
    def filter_line_29(self, data):
        """Filtrera störningar för linje 29"""
        if not data:
            return []
        
        # Om data kommer från scraping
        if data.get("source") == "website_scraping":
            if data.get("has_disruption"):
                return [{
                    "header": "Möjlig störning upptäckt",
                    "details": "Linje 29 nämns på SL:s störningssida. Kontrollera sl.se för detaljer.",
                    "timestamp": datetime.now().isoformat()
                }]
            return []
        
        # Standard API-format
        disruptions = []
        
        if "ResponseData" in data:
            for item in data.get("ResponseData", []):
                # Kontrollera TrafficTypes
                if "TrafficTypes" in item:
                    for traffic_type in item["TrafficTypes"]:
                        # Kolla om det är buss och innehåller linje 29
                        if traffic_type.get("Type") == "bus":
                            events = item.get("Events", [])
                            for event in events:
                                message = event.get("Message", "")
                                expanded = event.get("Expanded", "")
                                
                                # Kolla om linje 29 nämns
                                if LINE_TO_MONITOR in message or LINE_TO_MONITOR in expanded or \
                                   LINE_NAME.lower() in message.lower() or LINE_NAME.lower() in expanded.lower():
                                    disruptions.append({
                                        "header": message,
                                        "details": expanded,
                                        "severity": event.get("SeverityCode", 0),
                                        "timestamp": event.get("Created", "")
                                    })
        
        return disruptions
    
    def load_previous_state(self):
        """Ladda tidigare tillstånd från fil"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"⚠️  Kunde inte läsa tidigare tillstånd: {e}")
        return {}
    
    def save_state(self, disruptions):
        """Spara nuvarande tillstånd till fil"""
        state = {
            "timestamp": datetime.now().isoformat(),
            "disruptions": disruptions,
            "count": len(disruptions)
        }
        
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"⚠️  Kunde inte spara tillstånd: {e}")
    
    def send_notification(self, disruptions, notification_type="new"):
        """Skicka notifikation om störningar"""
        if notification_type == "new":
            title = f"⚠️ NY störning på linje {LINE_TO_MONITOR} ({LINE_NAME})"
        elif notification_type == "resolved":
            title = f"✅ Störning löst på linje {LINE_TO_MONITOR}"
        else:
            title = f"ℹ️ Störning på linje {LINE_TO_MONITOR}"
        
        if disruptions:
            message = f"{title}\n\n"
            for idx, d in enumerate(disruptions, 1):
                message += f"{idx}. {d.get('header', 'Störning')}\n"
                if d.get('details'):
                    details = d['details']
                    if len(details) > 200:
                        details = details[:200] + "..."
                    message += f"   {details}\n"
                message += "\n"
            message += "\nKontrollera: https://sl.se/reseplanering/trafiklaget"
        else:
            message = f"{title}\n\nAlla störningar på Näsbyparkslinjen har lösts!"
        
        self.log(message)
        
        # Skicka email
        if notification_type in ["new", "resolved"]:
            self.send_email_notification(title, message)
    
    def send_email_notification(self, subject, body):
        """Skicka email-notifikation"""
        email_from = os.environ.get("EMAIL_FROM")
        email_to = os.environ.get("EMAIL_TO")
        email_password = os.environ.get("EMAIL_PASSWORD")
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        
        if not all([email_from, email_to, email_password]):
            self.log("⚠️  Email inte konfigurerat (OK för test)")
            return
        
        try:
            msg = MIMEMultipart()
            msg["From"] = email_from
            msg["To"] = email_to
            msg["Subject"] = subject
            
            msg.attach(MIMEText(body, "plain", "utf-8"))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(email_from, email_password)
            server.send_message(msg)
            server.quit()
            
            self.log("📧 Email-notifikation skickad!")
            
        except Exception as e:
            self.log(f"⚠️  Kunde inte skicka email: {e}")
    
    def run(self):
        """Huvudloop - kontrollera trafikläget"""
        self.log("=" * 70)
        self.log(f"🚌 Kontrollerar trafikläget för linje {LINE_TO_MONITOR} ({LINE_NAME})...")
        
        if not self.api_key:
            self.log("ℹ️  Ingen API-nyckel - använder alternativa metoder")
        
        # Hämta nuvarande störningar
        data = self.fetch_disruptions()
        
        if data is None:
            self.log("⚠️  Kunde inte hämta data. Försöker igen nästa gång.")
            return
        
        current_disruptions = self.filter_line_29(data)
        
        # Ladda tidigare tillstånd
        previous_state = self.load_previous_state()
        previous_count = previous_state.get("count", 0)
        current_count = len(current_disruptions)
        
        # Analysera ändringar
        if current_count > 0:
            if previous_count == 0:
                # Nya störningar
                self.log(f"🆕 NYA STÖRNINGAR på linje {LINE_TO_MONITOR}!")
                self.send_notification(current_disruptions, "new")
            elif current_count != previous_count:
                # Antal ändrat
                self.log(f"🔄 Störningar uppdaterade ({current_count} st)")
                self.send_notification(current_disruptions, "updated")
            else:
                # Samma antal
                self.log(f"📊 Pågående: {current_count} störning(ar)")
        else:
            if previous_count > 0:
                # Störningar lösta
                self.log(f"✅ Alla störningar på linje {LINE_TO_MONITOR} har lösts!")
                self.send_notification([], "resolved")
            else:
                # Inga störningar
                self.log(f"✅ Inga störningar på linje {LINE_TO_MONITOR}")
        
        # Spara tillstånd
        self.save_state(current_disruptions)
        self.log("✓ Kontroll slutförd")

if __name__ == "__main__":
    monitor = SLMonitorSimple()
    monitor.run()
