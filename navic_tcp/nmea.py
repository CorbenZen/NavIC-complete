"""Generic NMEA 0183 fix/satellite decoder, not a claim about a specific IVTD receiver.

This module is an adapter primitive. The running TCP service continues to accept its
versioned JSON protocol until a receiver-specific transport/framing document is available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


class NmeaError(ValueError):
    pass


_TALKERS={"GP":"gps","GL":"glonass","GA":"galileo","GB":"beidou","BD":"beidou","GQ":"qzss","GI":"navic"}
_SYSTEM_IDS={1:"gps",2:"glonass",3:"galileo",4:"beidou",5:"qzss",6:"navic"}
_FIX_MODES={"A","D","E","F","M","P","R","S"}


def _coordinate(value: str, hemisphere: str, degree_digits: int) -> float:
    if not value or hemisphere not in ("N","S","E","W"):
        raise NmeaError("missing or invalid NMEA coordinate")
    try:
        raw=float(value)
    except ValueError:
        raise NmeaError("invalid NMEA coordinate") from None
    degrees=int(raw//100); minutes=raw-degrees*100
    result=degrees+minutes/60
    limit=90 if degree_digits==2 else 180
    if not isfinite(result) or minutes>=60 or result>limit or (result==limit and minutes>0):
        raise NmeaError("NMEA coordinate outside valid range")
    if hemisphere in ("S","W"):result=-result
    return result


def _clock(value: str) -> tuple[int,int,float]:
    try:
        h=int(value[0:2]);m=int(value[2:4]);s=float(value[4:])
    except (ValueError,IndexError):raise NmeaError("invalid NMEA UTC time") from None
    if h>23 or m>59 or not 0<=s<60:raise NmeaError("invalid NMEA UTC time")
    return h,m,s


def _utc(time_value: str, date_value: str | None = None) -> str:
    h,m,s=_clock(time_value);micro=round((s-int(s))*1_000_000)
    if not date_value:raise NmeaError("full UTC timestamp requires a date-bearing NMEA sentence")
    if len(date_value)!=6 or not date_value.isdigit():raise NmeaError("invalid NMEA date")
    day,month,yy=int(date_value[:2]),int(date_value[2:4]),int(date_value[4:6])
    year=2000+yy if yy<80 else 1900+yy
    try:dt=datetime(year,month,day,h,m,int(s),micro,tzinfo=timezone.utc)
    except ValueError:raise NmeaError("invalid NMEA date/time") from None
    return dt.isoformat(timespec="milliseconds").replace("+00:00","Z")


def _checksum(sentence: str) -> str:
    body=sentence.strip()
    if not body.startswith("$") or "*" not in body:raise NmeaError("NMEA checksum is required")
    data,checksum=body[1:].rsplit("*",1)
    if len(checksum)!=2:
        raise NmeaError("invalid NMEA checksum")
    value=0
    for ch in data:value^=ord(ch)
    try:expected=int(checksum,16)
    except ValueError:raise NmeaError("invalid NMEA checksum") from None
    if value!=expected:raise NmeaError("NMEA checksum mismatch")
    return data


class NmeaDecoder:
    """Incrementally retain sentence metadata and return a normalized view per sentence."""
    def __init__(self):
        self.state={"fix_valid":None,"latitude":None,"longitude":None,"timestamp":None,
                    "altitude_m":None,"speed_kmh":None,"course":None,"satellites_used":None,
                    "satellites_in_view":None,"pdop":None,"hdop":None,"vdop":None,
                    "constellations":[],"satellites":[],"mode_indicator":None}
        self._gsv:dict[str,dict]={}

    @staticmethod
    def _float(fields,index):
        if len(fields)<=index or fields[index]=="":return None
        try:value=float(fields[index])
        except ValueError:raise NmeaError("invalid numeric NMEA field") from None
        if not isfinite(value):raise NmeaError("non-finite NMEA field")
        return value

    def protocol_metadata(self) -> dict:
        """Return only the version-1 TCP protocol's optional, validated GNSS fields."""
        result={}
        for key in ("fix_valid","altitude_m","satellites_in_view","satellites_used","pdop","hdop","vdop","constellations"):
            value=self.state.get(key)
            if value is not None:result[key]=value
        sats=[]
        for satellite in self.state.get("satellites",[]):
            item={key:satellite[key] for key in ("constellation","satellite_id","signal_id","cn0_db_hz","elevation_deg","azimuth_deg") if satellite.get(key) is not None}
            if "satellite_id" in item:sats.append(item)
        if sats:result["satellites"]=sats
        return result

    def feed(self, sentence: str) -> dict:
        data=_checksum(sentence);fields=data.split(",")
        tag=fields[0]
        if len(tag)!=5 or not tag.startswith("G"):
            raise NmeaError("unsupported NMEA talker/sentence identifier")
        talker,suffix=tag[:2],tag[2:]
        system=_TALKERS.get(talker)
        out={"talker_id":talker,"sentence_type":suffix}
        if suffix in ("GGA","GNS"):
            if len(fields)<10:raise NmeaError(f"short {suffix} sentence")
            h,m,s=_clock(fields[1]);self.state["time_utc"]=f"{h:02d}:{m:02d}:{s:06.3f}Z"
            self.state["timestamp"]=None
            self.state["latitude"]=_coordinate(fields[2],fields[3],2) if fields[2] else None
            self.state["longitude"]=_coordinate(fields[4],fields[5],3) if fields[4] else None
            if suffix=="GGA":
                try:quality=int(fields[6] or "0");used=int(fields[7] or "0")
                except ValueError:raise NmeaError("invalid GGA fix/satellite count") from None
                self.state["fix_valid"]=quality>0
                self.state["satellites_used"]=used
                self.state["hdop"]=self._float(fields,8)
                self.state["altitude_m"]=self._float(fields,9)
            else:
                mode=fields[6];valid=any(c in _FIX_MODES for c in mode)
                self.state["fix_valid"]=valid
                self.state["mode_indicator"]=mode or None
                try:used=int(fields[7] or "0")
                except ValueError:raise NmeaError("invalid GNS satellite count") from None
                self.state["satellites_used"]=used
                self.state["hdop"]=self._float(fields,8)
                self.state["altitude_m"]=self._float(fields,9)
            if system:self.state["constellations"]=sorted(set(self.state["constellations"])|{system})
        elif suffix=="RMC":
            if len(fields)<10:raise NmeaError("short RMC sentence")
            self.state["fix_valid"]=fields[2]=="A"
            if self.state["fix_valid"]:
                self.state["latitude"]=_coordinate(fields[3],fields[4],2)
                self.state["longitude"]=_coordinate(fields[5],fields[6],3)
            self.state["timestamp"]=_utc(fields[1],fields[9])
            knots=self._float(fields,7);self.state["speed_kmh"]=knots*1.852 if knots is not None else None
            self.state["course"]=self._float(fields,8)
            if system:self.state["constellations"]=sorted(set(self.state["constellations"])|{system})
        elif suffix=="VTG":
            if len(fields)<9:raise NmeaError("short VTG sentence")
            self.state["course"]=self._float(fields,1)
            kmh=self._float(fields,7);knots=self._float(fields,5)
            self.state["speed_kmh"]=kmh if kmh is not None else knots*1.852 if knots is not None else None
        elif suffix=="GSA":
            if len(fields)<18:raise NmeaError("short GSA sentence")
            self.state["satellites_used"]=sum(1 for satellite in fields[3:15] if satellite)
            self.state["pdop"]=self._float(fields,15);self.state["hdop"]=self._float(fields,16);self.state["vdop"]=self._float(fields,17)
            # NMEA 4.11 optionally appends a system ID (1 GPS ... 6 NavIC).
            if len(fields)>18 and fields[18].isdigit():
                selected=_SYSTEM_IDS.get(int(fields[18]))
                if selected:self.state["constellations"]=sorted(set(self.state["constellations"])|{selected})
            if system:self.state["constellations"]=sorted(set(self.state["constellations"])|{system})
        elif suffix=="GSV":
            if len(fields)<4:raise NmeaError("short GSV sentence")
            try:total=int(fields[1]);index=int(fields[2]);in_view=int(fields[3])
            except ValueError:raise NmeaError("invalid GSV sequence/count") from None
            if total<1 or not 1<=index<=total or not 0<=in_view<=255:raise NmeaError("invalid GSV sequence/count")
            key=talker;batch=self._gsv.setdefault(key,{"total":total,"parts":{},"in_view":in_view})
            if batch["total"]!=total:batch={"total":total,"parts":{},"in_view":in_view};self._gsv[key]=batch
            sats=[]
            for pos in range(4,len(fields)-1,4):
                if not fields[pos]:continue
                try:sid=int(fields[pos]);elevation=int(fields[pos+1]) if fields[pos+1] else None;azimuth=int(fields[pos+2]) if fields[pos+2] else None;cn0=float(fields[pos+3]) if fields[pos+3] else None
                except ValueError:raise NmeaError("invalid GSV satellite record") from None
                item={"satellite_id":sid,"elevation_deg":elevation,"azimuth_deg":azimuth,"cn0_db_hz":cn0}
                if system:item["constellation"]=system
                sats.append(item)
            batch["parts"][index]=sats
            if index==total:
                gathered=[s for part in sorted(batch["parts"]) for s in batch["parts"][part]]
                # NMEA 4.11 may append a signal ID after the final satellite group.
                if len(fields[4:])%4==1:
                    signal_id=fields[-1]
                    for sat in gathered:sat["signal_id"]=signal_id
                self.state["satellites_in_view"]=in_view
                self.state["satellites"]=[dict(s) for s in gathered]
                if system:self.state["constellations"]=sorted(set(self.state["constellations"])|{system})
                self._gsv.pop(key,None)
        else:
            raise NmeaError(f"unsupported NMEA sentence type {suffix}")
        out.update(self.state)
        out["talker_constellation"]=system
        return out
