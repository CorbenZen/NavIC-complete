# IVTD GNSS compatibility and evidence

## Hardware compatibility result: unverified

The repository contains no exact GNSS receiver manufacturer/model, receiver datasheet, firmware image, UART/NMEA capture, receiver configuration transcript, or connected IVTD. README describes the receiver, STM32 and modem as future hardware integration. The device registry and telemetry simulator are explicitly fictional. Therefore this project cannot verify any constellation capability or receiver configuration command.

| Capability | Status | Evidence available in this repository |
|---|---|---|
| Exact receiver model | Unverified | No receiver part number or manufacturer is recorded. “E1A” alone does not identify a receiver model. |
| NavIC / IRNSS | Unverified | No receiver datasheet/output or physical fix. |
| GPS | Unverified | No receiver datasheet/output or physical fix. |
| GLONASS | Unverified | No receiver datasheet/output or physical fix. |
| Galileo | Unverified | No receiver datasheet/output or physical fix. |
| BeiDou | Unverified | No receiver datasheet/output or physical fix. |
| QZSS | Unverified | No receiver datasheet/output or physical fix. |
| Frequency bands/signals | Unverified | No receiver model or RF specifications. |
| NMEA sentence set/output version | Unverified | No raw receiver output capture or firmware documentation. |
| Simultaneous constellation operation | Unverified | No model specification or configured receiver log. |
| Documented constellation configuration commands | Unverified | No command manual/firmware interface. |

“E1-A” is also used as the name of a Galileo E1 signal component, not enough by itself to identify a module; the European Space Agency GNSS reference describes E1-A as a Galileo PRS component. See [ESA GNSS reference, Galileo signal components](https://gssc.esa.int/navipedia/GNSS_Book/ESA_GNSS-Book_TM-23_Vol_I.pdf#page=31). The project team must provide the receiver's full manufacturer and part number before claiming it supports NavIC or any other constellation.

## Software support added

- Existing TCP input remains version 1 newline-delimited JSON. No undocumented raw-NMEA framing was added to the TCP listener.
- JSON telemetry may include an optional `gnss` object with fix validity, altitude in metres, satellites in view, satellites used, PDOP/HDOP/VDOP, explicitly identified constellations, and per-satellite ID/signal metadata.
- Invalid fixes with `gnss.fix_valid: false` are rejected as stored location points. Existing packets without GNSS metadata remain accepted and preserve ordinary GPS-coordinate tracking.
- `navic_tcp/nmea.py` is a generic NMEA sentence adapter for GGA, RMC, GSA, GSV, GNS and VTG. It validates checksums and coordinates, keeps missing values unknown, distinguishes talker IDs, supports explicit `GI` talker and GSA System ID 6 NavIC labels, and does not infer constellations from the mixed `GN` talker or from location.
- The parser is not connected to the IVTD TCP listener. It is a reusable receiver-adapter component; mapping it into the product requires confirmation of actual serial/TCP transport, sentence version, talker IDs, checksum policy and receiver behavior.
- `LocationHistory` stores the optional GNSS fields and JSON metadata. Additive startup/seed migrations add nullable columns and leave existing history records intact.
- Device details show fix diagnostics and report-received constellation metadata. Every constellation capability is explicitly “unsupported or unverified” until device-specific evidence is configured. A reported satellite is labeled as receiver-reported, not verified physical reception.

## Validation performed

Generic NMEA syntax fixtures exercise GPS talker GGA/RMC/VTG, NavIC GI GSV, GSA System ID 6, mixed GN GNS with unknown system attribution, unavailable satellite fields, invalid fixes, invalid coordinates and checksum rejection. These are parser unit fixtures, not captures from the IVTD receiver and not proof of satellite reception. TCP/database tests verify optional metadata validation, persistence and WebSocket broadcast using the existing JSON protocol.
