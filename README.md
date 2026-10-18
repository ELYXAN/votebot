# 🗳️ Votebot

Ein Twitch-Bot, der **Votes über Kanalpunkte** trackt: Zuschauer lösen eine
Belohnung ein und nennen ein Spiel, Votebot erkennt den Namen (auch mit Tippfehlern),
trägt den Vote in dein **Google Sheet** ein, sortiert die Rangliste und postet eine
**Chat-Benachrichtigung**. Optional beantwortet ein **AI-Chat** Zuschauerfragen.

Alles wird über ein **lokales Web-Dashboard** eingerichtet und bedient – du musst
keine Konfigurationsdateien von Hand bearbeiten.

---

## 🚀 Schnellstart

### Voraussetzung
- [Python 3.9+](https://www.python.org/downloads/) installiert.

### Starten
- **Linux / macOS:** im Terminal `./start.sh` ausführen
- **Windows:** Doppelklick auf `start.bat`

Beim ersten Start richtet sich Votebot selbst ein (virtuelle Umgebung + Pakete) und
öffnet anschließend automatisch das Dashboard unter
**http://localhost:17563**. Ab dann führt dich der Einrichtungs-Assistent Schritt für
Schritt durch alles Weitere.

---

## 🧭 Der Einrichtungs-Assistent

Der Wizard führt dich Schritt für Schritt – jeder wird direkt im Browser erledigt.
(Im **End-User-Modus** entfällt Schritt 1, und Schritt 5 braucht nur das Teilen des Sheets.)

1. **Twitch-App anlegen** – einmalig eine kostenlose App in der
   [Twitch Developer Console](https://dev.twitch.tv/console/apps/create) erstellen.
   Die benötigte *OAuth Redirect URL* zeigt dir der Wizard zum Kopieren an.
2. **Als Streamer anmelden** – ein Klick, Login über Twitch. **Kein Code-Kopieren mehr** –
   die Anmeldung wird automatisch zurückgeleitet.
3. **Chat-Account wählen** – Benachrichtigungen über deinen eigenen Account oder einen
   separaten Bot-Account.
4. **Belohnungen anlegen** – Votebot erstellt die Kanalpunkte-Belohnungen (Normaler Vote,
   Super Vote, …) direkt auf deinem Kanal. Namen, Kosten und Vote-Gewicht sind einstellbar.
5. **Google Sheet verbinden** – Service-Account-JSON hochladen, Sheet-Link eintragen,
   Verbindung testen. Fertig.
6. **AI-Chat (optional)** – OpenAI-Key hinterlegen oder überspringen.

> 💡 **Warum legt Votebot die Belohnungen selbst an?** Twitch erlaubt es nur, Belohnungen
> über die API als „erledigt" zu markieren, wenn sie von *derselben* App erstellt wurden.
> Deshalb erstellt Votebot sie für dich – manuell im Dashboard angelegte Belohnungen
> ließen sich nicht verwalten.

---

## 🎁 Zwei Betriebsmodi: Entwickler vs. End-User

Votebot erkennt automatisch zwei Modi:

- **Entwickler-Modus** (bei dir): kein `app_credentials.json` vorhanden → der volle Wizard
  inkl. Twitch-Developer-Console-Schritt wird angezeigt. Dieser Modus ist nur für dich gedacht,
  der die App einmal einrichtet.
- **End-User-Modus** (für Weitergabe): es liegt ein `app_credentials.json` bei → der
  Twitch-Developer-Schritt wird **übersprungen**, weil die Twitch-App schon mitgeliefert wird.
  Wird zusätzlich ein Service-Account mitgeliefert, müssen End-User auch keine Google Cloud
  Console öffnen – sie teilen nur ihr Sheet mit der angezeigten E-Mail.

### Eine Version zum Weitergeben erstellen

1. Richte Votebot bei dir im **Entwickler-Modus** vollständig ein (Twitch-App + Google Sheets).
2. Geh im Wizard zum letzten Schritt „Fertig" → **„Version für Weitergabe erstellen"** →
   Haken bei „Service-Account mitliefern" → **app_credentials.json erzeugen**.
3. Gib den Ordner weiter – **mit** `app_credentials.json`, `service_account.json` und `votebot/`,
   aber **ohne** deine persönliche `config.json` (die enthält deine eigenen Logins).

> ⚠️ `app_credentials.json` und `service_account.json` enthalten deine Zugangsdaten.
> Gib sie nur an Leute weiter, denen du vertraust. Alle End-User teilen sich dein
> Twitch-API- und Google-Kontingent (für kleine Runden unkritisch).

Um selbst wieder in den Entwickler-Modus zu wechseln: `app_credentials.json` löschen
(oder im Wizard „Bundle entfernen").

---

## 📊 Dashboard

Nach der Einrichtung bietet das Dashboard:

- **Start/Stopp** des Bots per Knopfdruck
- **Live-Log** aller Ereignisse in Echtzeit
- **Ranking** direkt aus dem Google Sheet
- **Manueller Vote** (z. B. für Votes außerhalb von Twitch)
- **Belohnungen verwalten** – jederzeit neue hinzufügen oder entfernen
- **Einstellungen** – Fuzzy-Match-Schwelle, AI-Modell/Key, Sheet-Test

---

## 📄 Google Sheet

- Spalte **A** = Votes (Zahl), Spalte **B** = Spielname
- Bei einem leeren Blatt legt Votebot die Kopfzeile selbst an
- Das Sheet muss mit der **E-Mail des Service-Accounts** geteilt werden
  (als *Bearbeiter*). Die E-Mail zeigt dir der Wizard nach dem JSON-Upload an.

So kommst du an die Service-Account-JSON: in der
[Google Cloud Console](https://console.cloud.google.com/) ein Projekt anlegen →
„Google Sheets API" aktivieren → *Dienstkonto* erstellen → *Schlüssel* (JSON) herunterladen.

---

## 🔒 Sicherheit

- Alle Zugangsdaten bleiben **lokal** in `config.json` und `service_account.json`.
- Secrets werden nie im Log ausgegeben und nie unmaskiert an die Oberfläche gesendet.
- Gib diese Dateien **nicht** weiter.

---

## 🛠️ Projektstruktur

```
votebot/
  config.py         Konfiguration, Schema & Migration
  twitch.py         OAuth, Tokens, Rewards, Chat
  sheets.py         Google-Sheets-Anbindung
  ai.py             OpenAI-Chat + Websuche
  bot.py            Kern-Bot (Listener + Verarbeitung)
  logging_setup.py  Live-Log fürs Dashboard
  web/              FastAPI-App, Wizard & Dashboard
run.py              Einstiegspunkt
start.sh / .bat     Komfort-Starter (venv + Install + Start)
```

> Das alte Einzelskript `vote_tracker.py` liegt als Referenz bei und wird nicht mehr
> benötigt – es kann gelöscht werden.

---

## ❓ Fehlerbehebung

- **„Reward anlegen verweigert (403)"** – Kanalpunkte-Belohnungen gibt es nur für
  Twitch-**Affiliates/Partner**.
- **Sheet-Test schlägt fehl** – ist das Sheet mit der Service-Account-E-Mail geteilt und
  die *Google Sheets API* im Projekt aktiviert?
- **Twitch-Login kommt nicht zurück** – ist die *Redirect URL* in der Twitch-App exakt
  `http://localhost:17563/oauth/callback` (ohne abschließenden Schrägstrich)?
- **Chat-Nachrichten kommen nicht an** – der sendende Account braucht den Scope
  `user:write:chat`; ggf. im Wizard neu anmelden.

---

Entwickelt mit ❤️ von **ELYXAN / KUS_SWAT_**
