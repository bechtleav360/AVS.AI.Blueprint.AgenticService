# Asset-Typen (Datenhoheit & Technologische Unabhängigkeit)

- [A01 – Cloud Software](./A01%20-%20Cloud%20Software/README.md) Fokus auf Datenresidenz, Subprozessoren, Export und Löschung. Beispiele: CRM, Kollaboration, Tickets. Risiken: Rechtsraumzugriffe, Feature‑Lock‑in, Weiterverwendung.
- [A02 – Self‑Hosted Software](./A02%20-%20Self-Hosted%20Software/README.md) Volle Kontrolle über Laufzeit und Daten. Beispiele: eigene Wikis, Issue‑Tracker, BI. Risiken: hoher Betriebsaufwand, Abhängigkeit von Hersteller‑Stacks.
- [A03 – Endpoint Software](./A03%20-%20Endpoint%20Software/README.md) OS, Clients und Agenten mit zentralen Policies. Beispiele: Office‑Suite, EDR, Browser. Risiken: Telemetrie, erzwungene Updates, proprietäre Formate.
- [A04 – IT‑Service‑Provider (MSP/Outsourcing)](./A04%20-%20IT_Service_Provider/README.md) Steuerung von Zugriffen und Nachweisen. Risiken: Schattenverarbeitung, Aufbewahrung ohne Kontrolle, Personenabhängigkeiten.
- [A05 – Backup/Archiv & Desaster Recovery](./A05%20-%20Archives/README.md) Orte und Kopien von Daten, Aufbewahrung und Löschung. Beispiele: Immutable, WORM, Offsite. Risiken: Restdaten, Kopien über Regionen, Egress‑Kosten.
- [A06 – Netzwerk‑Komponenten & ‑Infrastruktur](./A06%20-%20Networking%20Hardware/README.md) Transparenz der Pfade und Standorte. Beispiele: Firewalls, SD‑WAN, Switches. Risiken: Transit durch Drittländer, intransparentes Routing.
- [A07 – Server‑Hardware & Edge/Datacenter‑Infrastruktur](./A07%20-%20Server_Hardware/README.md) Standorte und Vertrauenskette beim Boot. Beispiele: Rack‑Server, HCI, Edge. Risiken: Remotezugriff durch Hersteller, Datenabfluss bei RMA.
- [A08 – PaaS (Managed Platforms)](./A08%20-%20PaaS/README.md) Schlüsselhoheit und Region. Beispiele: Managed Datenbanken, Functions, Queues. Risiken: Control‑Plane‑Zugriff, proprietäre APIs.
- [A09 – IaaS](./A09%20-%20IaaS/README.md) Compute, Storage und Networking als Basis. Beispiele: VMs, Bare Metal, VPC/VNET. Risiken: Replikation über Grenzen, Egress‑Lock‑in.
- [A10 – Endpoint Hardware](./A10%20-%20Endpoint%20Hardware/README.md) Eigentum und Schutz von Geräten und Datenträgern. Beispiele: Laptops, Smartphones, verschlüsselte USB‑Medien. Risiken: physischer Abfluss, Missbrauch von Schnittstellen.

- Integration/API/ETL/iPaaS Verortung je nach Betriebsmodell: [A01](./A01%20-%20Cloud%20Software/README.md), [A02](./A02%20-%20Self-Hosted%20Software/README.md), [A08](./A08%20-%20PaaS/README.md). Risiken: Schattenübertragungen, intransparente Subprozessoren.
- Identität und Schlüsselmanagement Schwerpunkt auf [A08](./A08%20-%20PaaS/README.md). Themen: Admin‑Kontrolle, JIT/PAM, Kundenschlüssel. Risiken: zentrales Lock‑in, Schlüsselhaltung beim Anbieter.
