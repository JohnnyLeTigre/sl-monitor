#!/usr/bin/env python3
"""
SL Trafikläge Monitor - Ultra-enkel version
Kollar om linje 29 nämns på SL:s störningssida
"""

import requests
import json
import os
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time

# Konfiguration
LINE_TO_MONITOR = "29"
LINE_NAME = "Näsbyparkslinjen"
STATE_FILE = Path(__file__).parent / "sl_state.json"

class SLMonitorUltraSimple:
    def __init__(self):
        self.url = "https://sl.se/reseplanering/trafiklaget"
    
    def log(self, message):
        """Logga meddelanden (bara print i denna version)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
    
    def check_for_disruptions(self):
        """Kolla om linje 29 har störningar genom att hämta hemsidan"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            self.log("Hämtar SL:s störningssida...")
            response = requests.get(self.url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                self.log(f"⚠️ Hemsidan svarade med status {response.status_code}")
                return None
            
            content = response.text.lower()
            
            # Kolla om linje 29 eller Näsbyparkslinjen nämns
            has_line_29 = "linje 29" in content or " 29 " in content or "linje29" in content
            has_nasbyparken = "näsbypark" in content
            has_disruption_words = any(word in content for word in [
                "störning", "förseningar", "inställd", "ersättningsbuss", 
                "trafik", "problem", "avbrott"
            ])
            
            # Om linje 29 nämns OCH det finns störningsord i närheten
            if (has_line_29 or has_nasbyparken) and has_disruption_words:
                self.log(f"⚠️ Linje {LINE_TO_MONITOR} kan ha störningar (nämns på sidan)")
                
                # Försök hitta kontexten där linje 29 nämns
                lines = content.split('\n')
                relevant_context = []
                
                for i, line in enumerate(lines):
                    if "29" in line or "näsbypark" in line:
                        # Ta lite kontext runt omnämnandet
                        context_start = max(0, i - 2)
                        context_end = min(len(lines), i + 3)
                        context = ' '.join(lines[context_start:context_end])
                        if len(context) > 50:  # Bara om det är meningsfullt
                            relevant_context.append(context[:300])
                
                return {
                    "has_disruption": True,
                    "context": relevant_context[:2] if relevant_context else ["Störning upptäckt"],
                    "timestamp": datetime.now().isoformat()
                }
            else:
                self.log(f"✅ Linje {LINE_TO_MONITOR} nämns inte bland störningar")
                return {
                    "has_disruption": False,
                    "timestamp": datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            self.log("⏱️ Timeout - hemsidan svarade inte i tid")
            return None
        except requests.exceptions.RequestException as e:
            self.log(f"❌ Nätverksfel: {str(e)[:100]}")
            return None
        except Exception as e:
            self.log(f"❌ Oväntat fel: {str(e)[:100]}")
            return None
    
    def load_previous_state(self):
        """Ladda tidigare tillstånd från fil"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.log(f"⚠️ Kunde inte läsa tidigare tillstånd: {e}")
        return {"had_disruption": False}
    
    def save_state(self, has_disruption):
        """Spara nuvarande tillstånd till fil"""
        state = {
            "timestamp": datetime.now().isoformat(),
            "had_disruption": has_disruption
        }
        
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"⚠️ Kunde inte spara tillstånd: {e}")
    
    def send_email_notification(self, subject, body):
        """Skicka email-notifikation"""
        email_from = os.environ.get("EMAIL_FROM")
        email_to = os.environ.get("EMAIL_TO")
        email_password = os.environ.get("EMAIL_PASSWORD")
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        
        if not all([email_from, email_to, email_password]):
            self.log("ℹ️ Email inte konfigurerat")
            return False
        
        try:
            msg = MIMEMultipart()
            msg["From"] = email_from
            msg["To"] = email_to
            msg["Subject"] = subject
            
            msg.attach(MIMEText(body, "plain", "utf-8"))
            
            self.log(f"Skickar email till {email_to}...")
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(email_from, email_password)
            server.send_message(msg)
            server.quit()
            
            self.log("📧 Email skickat!")
            return True
            
        except Exception as e:
            self.log(f"⚠️ Kunde inte skicka email: {str(e)[:100]}")
            return False
    
    def run(self):
        """Huvudloop - kontrollera trafikläget"""
        self.log("=" * 70)
        self.log(f"🚌 SL Monitor - Linje {LINE_TO_MONITOR} ({LINE_NAME})")
        self.log("=" * 70)
        
        # Hämta nuvarande status
        result = self.check_for_disruptions()
        
        if result is None:
            self.log("⚠️ Kunde inte hämta data från SL. Försöker igen nästa gång.")
            self.log("=" * 70)
            return
        
        # Ladda tidigare tillstånd
        previous_state = self.load_previous_state()
        had_disruption_before = previous_state.get("had_disruption", False)
        has_disruption_now = result.get("has_disruption", False)
        
        # Analysera ändringar
        if has_disruption_now and not had_disruption_before:
            # NY STÖRNING!
            self.log("🆕 NY STÖRNING UPPTÄCKT!")
            
            subject = f"⚠️ Störning på linje {LINE_TO_MONITOR} ({LINE_NAME})"
            body = f"Störning upptäckt på linje {LINE_TO_MONITOR} - {LINE_NAME}\n\n"
            
            if result.get("context"):
                body += "Information från SL:\n"
                for ctx in result["context"]:
                    body += f"- {ctx}\n"
                body += "\n"
            
            body += f"Kontrollera: {self.url}\n\n"
            body += f"Upptäckt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            self.send_email_notification(subject, body)
            
        elif not has_disruption_now and had_disruption_before:
            # Störning löst!
            self.log("✅ STÖRNING LÖST!")
            
            subject = f"✅ Störning löst - Linje {LINE_TO_MONITOR}"
            body = f"Störningen på linje {LINE_TO_MONITOR} ({LINE_NAME}) verkar vara löst!\n\n"
            body += f"Linje {LINE_TO_MONITOR} nämns inte längre bland störningar på SL:s sida.\n\n"
            body += f"Kontrollera: {self.url}\n\n"
            body += f"Löst: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            self.send_email_notification(subject, body)
            
        elif has_disruption_now:
            # Pågående störning
            self.log(f"📊 Pågående störning på linje {LINE_TO_MONITOR}")
            
        else:
            # Inga störningar
            self.log(f"✅ Inga störningar på linje {LINE_TO_MONITOR}")
        
        # Spara nuvarande tillstånd
        self.save_state(has_disruption_now)
        
        self.log("✓ Kontroll slutförd")
        self.log("=" * 70)

if __name__ == "__main__":
    monitor = SLMonitorUltraSimple()
    monitor.run()
