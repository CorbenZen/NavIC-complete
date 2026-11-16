# IVTD Protocol — Open Questions for Hardware Integration

This document tracks unresolved questions about the IVTD (Intelligent Vehicle Tracking Device)
protocol and hardware. It is a living document; update it as answers arrive from the vendor
or field testing.

> **Status legend**
> - **OPEN** — no answer yet
> - **PARTIAL** — some information, needs confirmation
> - **RESOLVED** — documented in code/docs

---

## 1. Physical / Link layer

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 1.1 | Exact Quectel module model (e.g. EC25, EG91, LC79D)? | OPEN | Datasheet needed for AT command set and GNSS capabilities. |
| 1.2 | SIM form factor (nano, micro, eSIM)? | OPEN | Affects procurement and APN provisioning. |
| 1.3 | APN, username, password for the carrier? | OPEN | Required for PPP/NDIS bring-up; may differ per state. |
| 1.4 | Is the cellular link always-on or duty-cycled? | OPEN | Impacts TCP keep-alive and session timeout. |
| 1.5 | Does the device support TLS (MQTTS/HTTPS) or plain TCP only? | OPEN | Current server accepts plain TCP; TLS would need cert provisioning. |
| 1.6 | Antenna connectors (GNSS, LTE, Wi-Fi/BT)? | OPEN | External vs. embedded affects RF performance. |

---

## 2. GNSS / NavIC reception

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 2.1 | Which constellations does the receiver track simultaneously? | OPEN | GPS+NavIC? GPS+GLONASS+Galileo+BeiDou+NavIC? |
| 2.2 | Does it output NMEA 4.10/4.11 with talker IDs `GI`/`GQ`/`GB`? | OPEN | NavIC talker is `GI` (IRNSS), BeiDou is `GB`/`BD`, QZSS is `GQ`. |
| 2.3 | What is the NMEA sentence rate (1 Hz, 5 Hz, 10 Hz)? | OPEN | Higher rate = more data, more bandwidth. |
| 2.4 | Does it support L5/E5a/B2a bands for NavIC? | OPEN | L5 gives better accuracy and interference resistance. |
| 2.5 | Cold/ warm/ hot start TTFF (time to first fix)? | OPEN | Affects first-fix latency after ignition on. |
| 2.6 | Does the module output raw measurement data (pseudorange, carrier phase)? | OPEN | Needed for RTK/PPP if ever required. |
| 2.7 | Is SBAS (GAGAN) supported and enabled by default? | PARTIAL | Quectel modules typically support GAGAN; confirm enabled. |

---

## 3. Protocol framing (TCP payload)

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 3.1 | Is the JSON payload line-delimited (NDJSON) or length-prefixed? | RESOLVED | NDJSON per `navic_tcp/protocol.py`. |
| 3.2 | Maximum message size? | RESOLVED | 64 KiB (`MAX_MESSAGE_BYTES`). |
| 3.3 | Heartbeat / keep-alive interval expected by device? | OPEN | Server idle timeout is 300 s; device should send something before then. |
| 3.4 | Does the device expect an ACK for every message? | RESOLVED | Server sends `{"type":"ack","message_id":"..."}`. |
| 3.5 | Re-transmission policy on NACK / timeout? | OPEN | Implement exponential back-off on device side. |
| 3.6 | Device authentication: shared secret, per-device cert, or none? | PARTIAL | Optional `auth_token` field exists; policy TBD. |

---

## 4. Telemetry fields

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 4.1 | Does the device report `ignition` (boolean) reliably? | PARTIAL | Protocol requires it; verify hardware wiring. |
| 4.2 | Odometer: incremental from MCU or derived from GNSS? | OPEN | Affects accuracy; `odometer` field is optional in protocol. |
| 4.3 | `altitude_m`: WGS-84 ellipsoid or MSL (geoid)? | OPEN | NMEA GGA gives MSL; protocol stores as-is. |
| 4.4 | `pdop`/`hdop`/`vdop`: from which constellation solution? | OPEN | Mixed-constellation DOP vs. single-system. |
| 4.5 | `satellites_in_view` vs `satellites_used` counting method? | OPEN | Per-constellation or total? |
| 4.6 | Course resolution and update rate when speed ≈ 0? | OPEN | Course can jitter at standstill; protocol allows 0–359.99. |

---

## 5. Power / ignition behaviour

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 5.1 | Power supply: constant 12/24 V or switched with ignition? | OPEN | Determines if device stays alive for “ignition off” telemetry. |
| 5.2 | Sleep current draw (µA) in deep sleep? | OPEN | Battery drain concern for long-term parking. |
| 5.3 | Wake-up source: ignition sense, accelerometer, timer? | OPEN | Affects first-fix latency after stop. |
| 5.4 | Does the device buffer telemetry when cellular is down? | OPEN | Store-and-forward needed for tunnels/garages. |
| 5.5 | Buffer size and persistence (flash vs. RAM)? | OPEN | Data loss risk on power loss. |

---

## 6. Firmware / OTA

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 6.1 | OTA mechanism (MQTT, HTTPS, custom TCP)? | OPEN | Server may need to push updates. |
| 6.2 | Rollback / A-B partition scheme? | OPEN | Bricking risk if update fails. |
| 6.3 | Version reporting in telemetry (`fw_version` field)? | OPEN | Add to protocol if not present. |
| 6.4 | Configuration over-the-air (APN, server IP, intervals)? | OPEN | Remote re-provisioning avoids truck rolls. |

---

## 7. Mechanical / Environmental

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 7.1 | IP rating (IP67, IP69K)? | OPEN | Monsoon / bus wash exposure. |
| 7.2 | Operating temperature range? | OPEN | Bengaluru peaks ~38 °C; dashboard can hit 60 °C. |
| 7.3 | Vibration / shock spec (ISO 16750)? | OPEN | Bus chassis vibration is significant. |
| 7.4 | Mounting: OBD-II, splice harness, magnetic? | OPEN | Affects installation time and tamper resistance. |

---

## 8. Regulatory / Compliance

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 8.1 | WPC (Wireless Planning & Coordination) ETA certificate? | OPEN | Mandatory for cellular + GNSS in India. |
| 8.2 | BIS (Bureau of Indian Standards) registration? | OPEN | May be required for sale/deployment. |
| 8.3 | AIS-140 / UBS-II compliance (if applicable)? | OPEN | Only if used for public transport mandate. |

---

## 9. Data ownership / Privacy

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 9.1 | Who owns the raw NMEA / telemetry — college or vendor? | OPEN | Contract clause needed. |
| 9.2 | Data retention on device vs. cloud? | OPEN | GDPR/PDPB considerations if personal data inferred. |
| 9.3 | Driver ID / biometric linkage? | OPEN | Protocol has `driver_id`; verify hardware support. |

---

## 10. Test & Validation

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 10.1 | Reference NMEA log from a real device (static + dynamic)? | OPEN | Needed for `tests/fixtures/nmea/` and CI. |
| 10.2 | Bench test harness (GNSS simulator + LTE emulator)? | OPEN | Spirent / Rohde & Schwarz / lab-grade simulator. |
| 10.3 | Field trial route (HKBK campus loop) with ground truth? | OPEN | Compare reported position vs. surveyed points. |
| 10.4 | Long-duration soak test (72 h) with ignition cycles? | OPEN | Flushes memory leaks, buffer overflows. |

---

## How to use this document

1. **Assign an owner** for each OPEN item (vendor PM, college EE, or NavIC team).
2. **Update status** in-place when an answer arrives; move to RESOLVED with a reference (email date, spec rev, test report).
3. **Link from code**: each resolved item should be traceable to a protocol constant, schema column, or config default.
4. **Review at every sprint** — unresolved hardware questions block the “real device” milestone.

---

*Generated during the 2026-11-15 audit.  Source: `docs/ivtd-protocol-questions.md`.*