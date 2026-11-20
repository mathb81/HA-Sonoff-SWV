from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class Device:
    """Flat model for Sonoff SWV-ZFE device."""

    ieee: str = ""

    manufacturer: str = "SONOFF"

    model: str = ""

    firmware: str = ""

    hardware: str = ""

    friendly_name: str = ""

    # Device status

    battery: int | None = None

    linkquality: int | None = None

    state: str = "OFF"

    child_lock: str | None = None

    # General settings

    rain_delay: Any = None

    rain_delay_end_datetime: str | None = None

    # Durata scelta dall'utente per il ritardo pioggia (ore da adesso).
    rain_delay_hours: int | None = 24

    # Real time / statistics
    # Duration values are in minutes (Sonoff SWV-ZFE)

    real_time_irrigation_volume: int | None = None

    real_time_irrigation_duration: int | None = None

    daily_irrigation_volume: int | None = None

    daily_irrigation_duration: int | None = None

    hour_irrigation_volume: int | None = None

    hour_irrigation_duration: int | None = None

    # Schedule status

    irrigation_schedule_status: dict[str, Any] | None = None

    # Irrigation plan

    irrigation_plan_enabled: bool = False

    irrigation_plan_index: int | None = None

    irrigation_plan_create_datetime: str | None = None

    irrigation_plan_amount: int | None = None

    irrigation_plan_amount_unit: str | None = None

    irrigation_plan_mode: str | None = None

    irrigation_plan_loop_type: str | None = None

    irrigation_plan_duration: int | None = None

    irrigation_plan_total_duration: int | None = None

    irrigation_plan_interval_duration: int | None = None

    irrigation_plan_interval_days: int | None = None

    irrigation_plan_fail_safe: int | None = None

    irrigation_plan_start_time: str | None = None

    irrigation_plan_enable_date: str | None = None    

    irrigation_plan_monday: bool = False

    irrigation_plan_tuesday: bool = False

    irrigation_plan_wednesday: bool = False

    irrigation_plan_thursday: bool = False

    irrigation_plan_friday: bool = False

    irrigation_plan_saturday: bool = False

    irrigation_plan_sunday: bool = False

    irrigation_plan_settings: dict[str, Any] | None = None

    irrigation_plan_report: dict[str, Any] | None = None

    # Manual irrigation

    manual_default_settings: dict[str, Any] | None = None

    manual_irrigation_amount: int | None = 1

    manual_irrigation_mode: str | None = "capacity"

    manual_irrigation_duration: int | None = 1

    manual_irrigation_total_duration: int | None = 1

    manual_interval_duration: int | None = 1

    manual_fail_safe: int | None = 10

    # Valve state

    valve_abnormal_state: str | None = None

    # Alarm settings

    enable_alarm_water_shortage: bool = False

    enable_alarm_water_leak: bool = False

    enable_water_shortage_auto_close: bool = False

    alarm_water_leak_duration: int | None = 1

    alarm_water_shortage_duration: int | None = 2

    valve_alarm_settings: dict[str, Any] | None = None

    # Seasonal watering

    seasonal_watering_adjustment: dict[str, Any] | None = None

    seasonal_january: float | None = 1.0
    seasonal_february: float | None = 1.0
    seasonal_march: float | None = 1.0
    seasonal_april: float | None = 1.0
    seasonal_may: float | None = 1.0
    seasonal_june: float | None = 1.0
    seasonal_july: float | None = 1.0
    seasonal_august: float | None = 1.0
    seasonal_september: float | None = 1.0
    seasonal_october: float | None = 1.0
    seasonal_november: float | None = 1.0
    seasonal_december: float | None = 1.0

    # History records

    records_24_hours: list[dict[str, Any]] | None = None

    records_30_days: list[dict[str, Any]] | None = None

    records_180_days: list[dict[str, Any]] | None = None

    # Firmware update information

    update: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return device data as dictionary."""

        return asdict(self)

    def update_from_z2m_payload(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Update Device from Zigbee2MQTT payload."""

        device_info = payload.get(
            "device",
            {},
        )

        self.update = payload.get(
            "update",
            self.update,
        )

        self.ieee = device_info.get(
            "ieeeAddr",
            self.ieee,
        )

        self.manufacturer = device_info.get(
            "manufacturerName",
            self.manufacturer,
        )

        self.model = device_info.get(
            "model",
            self.model,
        )

        self.firmware = device_info.get(
            "softwareBuildID",
            self.firmware,
        )

        self.hardware = device_info.get(
            "hardwareVersion",
            self.hardware,
        )

        self.friendly_name = device_info.get(
            "friendlyName",
            self.friendly_name,
        )

        direct_fields = (
            "battery",
            "linkquality",
            "state",
            "rain_delay",
            "irrigation_schedule_status",
            "irrigation_plan_report",
            "valve_abnormal_state",
            "real_time_irrigation_volume",
            "real_time_irrigation_duration",
            "daily_irrigation_volume",
            "daily_irrigation_duration",
            "hour_irrigation_volume",
            "hour_irrigation_duration",
        )

        for field_name in direct_fields:

            if field_name in payload:

                setattr(
                    self,
                    field_name,
                    payload[field_name],
                )

        if "child_lock" in payload:

            self.child_lock = payload["child_lock"]

        # irrigation_plan_settings non viene letto: nei payload è solo l'eco,
        # in cache di Z2M, dell'ultimo piano scritto, e sovrascriverebbe
        # selettore e bozza del form a ogni messaggio del device.
        # I piani del device arrivano dal report (vedi coordinator).
        self.irrigation_plan_report = payload.get(
            "irrigation_plan_report",
            self.irrigation_plan_report,
        )

        self.seasonal_watering_adjustment = payload.get(
            "seasonal_watering_adjustment",
            self.seasonal_watering_adjustment,
        )

        # Per lo stesso motivo manual_default_settings non viene letto: è
        # l'eco dell'ultima scrittura, non una lettura del device.
        alarm = payload.get(
            "valve_alarm_settings",
            {},
        )

        if alarm:

            self.valve_alarm_settings = alarm

            self.enable_alarm_water_shortage = alarm.get(
                "enable_alarm_water_shortage",
                self.enable_alarm_water_shortage,
            )

            self.enable_alarm_water_leak = alarm.get(
                "enable_alarm_water_leak",
                self.enable_alarm_water_leak,
            )

            self.enable_water_shortage_auto_close = alarm.get(
                "enable_water_shortage_auto_close",
                self.enable_water_shortage_auto_close,
            )

            self.alarm_water_leak_duration = alarm.get(
                "alarm_water_leak_duration",
                self.alarm_water_leak_duration,
            )

            self.alarm_water_shortage_duration = alarm.get(
                "alarm_water_shortage_duration",
                self.alarm_water_shortage_duration,
            )

        self.records_24_hours = payload.get(
            "24_hours_records",
            self.records_24_hours,
        )

        self.records_30_days = payload.get(
            "30_days_records",
            self.records_30_days,
        )

        self.records_180_days = payload.get(
            "180_days_records",
            self.records_180_days,
        )

    def to_storage_dict(
        self,
    ) -> dict[str, Any]:
        """Convert Device to storage dictionary."""

        return asdict(self)

    @classmethod
    def from_storage_dict(
        cls,
        data: dict[str, Any],
    ) -> "Device":
        """Restore Device from storage dictionary."""

        device = cls()

        for key, value in data.items():

            if not hasattr(
                device,
                key,
            ):
                continue

            # Un valore None salvato non deve cancellare un default
            # già presente nel modello.
            if value is None and getattr(device, key) is not None:
                continue

            setattr(
                device,
                key,
                value,
            )

        return device