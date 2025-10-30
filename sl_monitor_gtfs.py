#!/usr/bin/env python3
"""
SL Trafikläge Monitor - Version för GTFS Sweden 3 Realtime API
Bevakar linje 29 (Näsbyparkslinjen)
"""

import requests
import json
import os
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.transit import gtfs_realtime_pb2

# Konfiguration
LINE_TO_MONITOR = "29"
LINE_NAME = "Näsbyparkslinjen"
STATE_FILE = Path(__file__).parent / "sl_state.json"
LOG_FILE = Path(__file__).parent / "sl_monitor.log"

class SLMonitorGTFS:
    def __init__(self):
        # GTFS Realtime API endpoint
        self.api_url = "https://opendata.samtrafiken.se/gtfs-sweden3/Service-Alerts.pb"
        self.api_key = os.environ.get("SL_API_KEY", "")
        
        if not self.api_key:
            self.log("⚠️  Ingen SL_API_KEY konfigurerad!")
            self.log("   Skaffa gratis API-nyckel på: https://www.trafiklab.se/")
            self.log("   API: 'GTFS Sweden 3 Realtime'")
            self.log("   Sätt sedan: export SL_API_KEY='din-nyckel'")
    
    def log(self, message):
        """Logga meddelanden till fil och konsol"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_message + "\n")
    
    def fetch_disruptions(self):
        """Hämta trafikstörningar från GTFS Realtime API"""
        if not self.api_key:
            return None
        
        try:
            params = {
                "key": self.api_key
            }
            
            response = requests.get(
                self.api_url, 
                params=params, 
                timeout=10
            )
            response.raise_for_status()
            
            # Parse GTFS Realtime Protobuf format
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            return feed
            
        except ImportError:
            self.log("⚠️  'gtfs-realtime-bindings' inte installerat!")
            self.log("   Installera: pip install gtfs-realtime-bindings")
            return None
        except requests.exceptions.Timeout:
            self.log("⏱️  Timeout vid anslutning till API")
            return None
        except requests.exceptions.RequestException as e:
            self.log(f"❌ Fel vid API-anrop: {e}")
            return None
        except Exception as e:
            self.log(f"❌ Fel vid parsing av data: {e}")
            return None
    
    def filter_line_29(self, feed):
        """Filtrera störningar för linje 29"""
        if not feed:
            return []
        
        line_disruptions = []
        
        for entity in feed.entity:
            if not entity.HasField('alert'):
                continue
            
            alert = entity.alert
            
            # Kontrollera om detta påverkar linje 29
            affects_line_29 = False
            
            for informed_entity in alert.informed_entity:
                # Kolla route_id (linjenummer)
                if informed_entity.HasField('route_id'):
                    route_id = informed_entity.route_id
                    # Route ID kan vara formaterat som "SL:29" eller bara "29"
                    if LINE_TO_MONITOR in route_id or route_id == LINE_TO_MONITOR:
                        affects_line_29 = True
                        break
            
            if affects_line_29:
                # Extrahera beskrivning på svenska om möjligt
                header = ""
                description = ""
                
                if alert.HasField('header_text'):
                    for translation in alert.header_text.translation:
                        if translation.language == 'sv' or not header:
                            header = translation.text
                
                if alert.HasField('description_text'):
                    for translation in alert.description_text.translation:
                        if translation.language == 'sv' or not description:
                            description = translation.text
                
                # Tidsperiod
                active_period = []
                for period in alert.active_period:
                    start = datetime.fromtimestamp(period.start) if period.HasField('start') else None
                    end = datetime.fromtimestamp(period.end) if period.HasField('end') else None
                    active_period.append({
                        'start': start.isoformat() if start else "",
                        'end': end.isoformat() if end else ""
                    })
                
                disruption = {
                    "alert_id": entity.id,
                    "header": header or "Störning",
                    "description": description,
                    "active_periods": active_period,
                    "cause": alert.cause if alert.HasField('cause') else 0,
                    "effect": alert.effect if alert.HasField('effect') else 0
                }
                
                line_disruptions.append(disruption)
        
        return line_disruptions
    
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
            "alert_ids": [d.get("alert_id") for d in disruptions]
        }
        
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"⚠️  Kunde inte spara tillstånd: {e}")
    
    def format_disruption_message(self, disruptions):
        """Formatera störningar till läsbar text"""
        message = ""
        
        for idx, d in enumerate(disruptions, 1):
            message += f"\n🔴 Störning {idx}:\n"
            message += f"   {d['header']}\n"
            
            if d['description']:
                desc = d['description']
                if len(desc) > 300:
                    desc = desc[:300] + "..."
                message += f"   {desc}\n"
            
            if d['active_periods']:
                for period in d['active_periods']:
                    if period['start']:
                        message += f"   Från: {period['start']}\n"
                    if period['end']:
                        message += f"   Till: {period['end']}\n"
            
            message += "\n"
        
        return message
    
    def send_notification(self, disruptions, notification_type="new"):
        """Skicka notifikation om störningar"""
        if notification_type == "new":
            title = f"⚠️ NY störning på linje {LINE_TO_MONITOR} ({LINE_NAME})"
        elif notification_type == "updated":
            title = f"🔄 Uppdaterad störning på linje {LINE_TO_MONITOR}"
        elif notification_type == "ongoing":
            title = f"ℹ️ Pågående störning på linje {LINE_TO_MONITOR}"
        else:  # resolved
            title = f"✅ Störning löst på linje {LINE_TO_MONITOR}"
        
        if disruptions:
            message = self.format_disruption_message(disruptions)
            full_message = f"{title}\n{message}\nKontrollera: https://sl.se/reseplanering/trafiklaget"
        else:
            full_message = f"{title}\n\nAlla störningar på Näsbyparkslinjen har lösts!"
        
        self.log(full_message)
        
        # Skicka desktop-notifikation
        self.send_desktop_notification(title, full_message)
        
        # Skicka email om konfigurerat
        if notification_type in ["new", "updated"]:
            self.send_email_notification(title, full_message)
    
    def send_desktop_notification(self, title, message):
        """Skicka desktop-notifikation"""
        try:
            import platform
            system = platform.system()
            
            short_msg = message.split('\n')[0:5]
            short_msg = '\n'.join(short_msg)[:300]
            
            if system == "Darwin":  # macOS
                safe_title = title.replace('"', '\\"').replace("'", "\\'")
                safe_msg = short_msg.replace('"', '\\"').replace("'", "\\'")
                os.system(f'''osascript -e 'display notification "{safe_msg}" with title "{safe_title}"' ''')
                
            elif system == "Linux":
                safe_title = title.replace('"', '\\"')
                safe_msg = short_msg.replace('"', '\\"')
                os.system(f'notify-send "{safe_title}" "{safe_msg}"')
                
            elif system == "Windows":
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast(title, short_msg, duration=10)
                except ImportError:
                    pass
                    
        except Exception as e:
            self.log(f"⚠️  Kunde inte skicka desktop-notifikation: {e}")
    
    def send_email_notification(self, subject, body):
        """Skicka email-notifikation"""
        email_from = os.environ.get("EMAIL_FROM")
        email_to = os.environ.get("EMAIL_TO")
        email_password = os.environ.get("EMAIL_PASSWORD")
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        
        if not all([email_from, email_to, email_password]):
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
        
        # Hämta nuvarande störningar
        feed = self.fetch_disruptions()
        
        if feed is None:
            self.log("⚠️  Kunde inte hämta data. Försöker igen nästa gång.")
            return
        
        current_disruptions = self.filter_line_29(feed)
        
        # Ladda tidigare tillstånd
        previous_state = self.load_previous_state()
        previous_ids = set(previous_state.get("alert_ids", []))
        current_ids = set(d.get("alert_id") for d in current_disruptions)
        
        # Analysera ändringar
        new_ids = current_ids - previous_ids
        resolved_ids = previous_ids - current_ids
        
        if current_disruptions:
            if new_ids:
                new_disruptions = [d for d in current_disruptions if d["alert_id"] in new_ids]
                self.log(f"🆕 {len(new_ids)} NY(A) STÖRNING(AR) på linje {LINE_TO_MONITOR}!")
                self.send_notification(new_disruptions, "new")
            elif resolved_ids and current_ids:
                self.log(f"🔄 Störningar uppdaterade på linje {LINE_TO_MONITOR}")
                self.send_notification(current_disruptions, "updated")
            else:
                self.log(f"📊 Pågående: {len(current_disruptions)} störning(ar) på linje {LINE_TO_MONITOR}")
        else:
            if previous_ids:
                self.log(f"✅ Alla störningar på linje {LINE_TO_MONITOR} har lösts!")
                self.send_notification([], "resolved")
            else:
                self.log(f"✅ Inga störningar på linje {LINE_TO_MONITOR}")
        
        # Spara nuvarande tillstånd
        self.save_state(current_disruptions)
        self.log("✓ Kontroll slutförd")

if __name__ == "__main__":
    monitor = SLMonitorGTFS()
    monitor.run()
