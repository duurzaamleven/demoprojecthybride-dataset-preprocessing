# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.bron: streamend lezen + schema-validatie (ontwerp §1, §4).

De fixture-zip bootst de twee geverifieerde schema-afwijkingen na (zie bron.py's module-docstring):
heatpump/boiler dragen kale kolomnamen, en household.csv heeft `participant_id` +
`wrong_elec_measurement`.
"""

from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from dph_preprocessing import bron as bron_mod

METADATA_CSV = (
    "velden,toelichting,document,eenheid_groot,eenheid_klein,resolutie,decimalen,extra_omschrijving\n"
    "location_id,id,ALL,,,,0,\n"
    "timestamp,tijd,ALL,secondes,s,1 s,0,\n"
    "e_consumed_low,x,dsmr.csv,kilowattuur,kWh,1 Wh,3,\n"
    "e_consumed_high,x,dsmr.csv,kilowattuur,kWh,1 Wh,3,\n"
    "e_delivered_low,x,dsmr.csv,kilowattuur,kWh,1 Wh,3,\n"
    "e_delivered_high,x,dsmr.csv,kilowattuur,kWh,1 Wh,3,\n"
    "v_gas_consumed,x,dsmr.csv,kuub,m3,0.001 m3,3,\n"
    "u_L1,x,dsmr.csv,volt,V,0.1 V,1,\n"
    "u_L2,x,dsmr.csv,volt,V,0.1 V,1,\n"
    "u_L3,x,dsmr.csv,volt,V,0.1 V,1,\n"
    "i_L1,x,dsmr.csv,ampere,A,1 A,0,\n"
    "i_L2,x,dsmr.csv,ampere,A,1 A,0,\n"
    "i_L3,x,dsmr.csv,ampere,A,1 A,0,\n"
    "p_consumed_L1,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "p_consumed_L2,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "p_consumed_L3,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "p_delivered_L1,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "p_delivered_L2,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "p_delivered_L3,x,dsmr.csv,kilowatt,kW,1 W,3,\n"
    "t_supply,x,kamstrup.csv,Celcius,C,0.01 C,2,\n"
    "t_return,x,kamstrup.csv,Celcius,C,0.01 C,2,\n"
    "e_thermal_system,x,kamstrup.csv,gigajoule,GJ,0.001 GJ,3,\n"
    "p_thermal_system,x,kamstrup.csv,kilowatt,kW,1 Wh,3,\n"
    "f_system,x,kamstrup.csv,liter/uur,L / h,1 L / h,0,\n"
    "heatpump_power,x,heatpump.csv,watt,W,0.1 W,1,\n"
    "heatpump_voltage,x,heatpump.csv,volt,V,0.1 V,1,\n"
    "heatpump_current,x,heatpump.csv,ampere,A,0.001 A,3,\n"
    "heatpump_energy,x,heatpump.csv,kilowattuur,kWh,1 Wh,3,\n"
    "boiler_power,x,boiler.csv,watt,W,0.1 W,1,\n"
    "boiler_voltage,x,boiler.csv,volt,V,0.1 V,1,\n"
    "boiler_current,x,boiler.csv,ampere,A,0.001 A,3,\n"
    "boiler_energy,x,boiler.csv,kilowattuur,kWh,1 Wh,3,\n"
    "temperature,x,room.csv,Celcius,C,0.1 C,1,\n"
    "humidity,x,room.csv,percentage,%,0.1%,1,\n"
    "station_code,x,knmi.csv,,,,0,\n"
    "T,x,knmi.csv,Celcius,0.1 C,0.1 C,0,\n"
    "FH,x,knmi.csv,meter/seconde,0.1 m/s,0.1 m/s,0,\n"
    "Q,x,knmi.csv,Joule/vierkantecentimeter,J/cm2,1 J/cm2,0,\n"
    "house_type,x,household.csv,,,,,\n"
    "construction_year,x,household.csv,year,y,20 years,0,\n"
    "surface,x,household.csv,square meter,m2,50 m2,0,\n"
    "energylabel,x,household.csv,,,,,\n"
    "number_of_inhabitants,x,household.csv,,,,,\n"
    "ownership,x,household.csv,,,,,\n"
    "gas_before_2,x,household.csv,cubic meter,m3,1 m3,0,\n"
    "gas_before_1,x,household.csv,cubic meter,m3,1 m3,0,\n"
    "electricity_before_2,x,household.csv,kilowatt-hour,kWh,1 Wh,0,\n"
    "electricity_before_1,x,household.csv,kilowatt-hour,kWh,1 Wh,0,\n"
    "has_low_heat_floor_heating,x,household.csv,,,,,\n"
    "has_high_heat_radiator_heating,x,household.csv,,,,,\n"
    "has_gas_furnace,x,household.csv,,,,,\n"
    "has_double_paned_glass,x,household.csv,,,,,\n"
    "has_roofinsulation,x,household.csv,,,,,\n"
    "has_wallinsulation,x,household.csv,,,,,\n"
    "has_floorinsulation,x,household.csv,,,,,\n"
)

HOUSEHOLD_CSV = (
    "participant_id,house_type,construction_year,surface,energylabel,number_of_inhabitants,"
    "ownership,gas_before_2,gas_before_1,electricity_before_1,electricity_before_2,has_gas_furnace,"
    "has_low_heat_floor_heating,has_high_heat_radiator_heating,has_double_paned_glass,"
    "has_roofinsulation,has_wallinsulation,has_floorinsulation,wrong_elec_measurement\n"
    "-ORiFQC6,vrijstaand,[1980-1999],[200 - 249],B,2+,particulier,2400.0,2200.0,3500.0,3600.0,0,1,1,1,1,1,0\n"
    "0RQyG6WX,2-onder-1-kap,2000=>,[100 - 149],A,2+,particulier,1271.0,1304.0,3000.0,2352.0,0,0,1,1,1,1,0\n"
)

DSMR_CSV = (
    "location_id,timestamp,e_consumed_high,e_consumed_low,e_delivered_high,e_delivered_low,i_L1,"
    "i_L2,i_L3,p_consumed_L1,p_consumed_L2,p_consumed_L3,p_delivered_L1,p_delivered_L2,"
    "p_delivered_L3,u_L1,u_L2,u_L3,v_gas_consumed\n"
    "-ORiFQC6,2022-02-07T11:00:00,8789.0,8969.0,8299.0,3433.0,4,4,4,0.0,0.0,0.0,1.1,0.9,1.1,230.0,230.0,230.0,5059.0\n"
    "0RQyG6WX,2022-02-07T11:00:00,1000.0,1000.0,0.0,0.0,1,1,1,0.5,0.5,0.5,0.0,0.0,0.0,230.0,230.0,230.0,100.0\n"
)

KAMSTRUP_CSV = (
    "location_id,timestamp,t_supply,t_return,e_thermal_system,p_thermal_system,f_system\n"
    "-ORiFQC6,2022-02-07T11:00:00,45.0,40.0,10.0,2.0,300.0\n"
    "0RQyG6WX,2022-02-07T11:00:00,30.0,29.0,1.0,0.0,0.0\n"
)

# Kaal: power,voltage,current,energy -- geen "heatpump_"/"boiler_"-prefix (zie module-docstring).
HEATPUMP_CSV = (
    "location_id,timestamp,power,voltage,current,energy\n"
    "-ORiFQC6,2022-02-07T11:00:00,500.0,230.0,2.0,3.0\n"
    "0RQyG6WX,2022-02-07T11:00:00,0.0,230.0,0.0,0.0\n"
)
BOILER_CSV = (
    "location_id,timestamp,power,voltage,current,energy\n"
    "-ORiFQC6,2022-02-07T11:00:00,0.0,230.0,0.0,0.0\n"
    "0RQyG6WX,2022-02-07T11:00:00,0.0,230.0,0.0,0.0\n"
)
ROOM_CSV = (
    "location_id,timestamp,temperature,humidity\n"
    "-ORiFQC6,2022-02-07T11:00:00,21.0,45.0\n"
    "0RQyG6WX,2022-02-07T11:00:00,20.0,50.0\n"
)
KNMI_CSV = (
    "timestamp,station_code,location_id,T,FH,Q\n"
    "2022-02-07T11:00:00,273,-ORiFQC6,70,60,100\n"
    "2022-02-07T11:00:00,273,0RQyG6WX,70,60,100\n"
)


@pytest.fixture
def dataset_zip(tmp_path):
    pad = tmp_path / "dph-dataset.zip"
    with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(bron_mod.METADATA_BESTANDSNAAM, METADATA_CSV)
        z.writestr(bron_mod.HOUSEHOLD_BESTANDSNAAM, HOUSEHOLD_CSV)
        z.writestr("dsmr.csv", DSMR_CSV)
        z.writestr("kamstrup.csv", KAMSTRUP_CSV)
        z.writestr("heatpump.csv", HEATPUMP_CSV)
        z.writestr("boiler.csv", BOILER_CSV)
        z.writestr("room.csv", ROOM_CSV)
        z.writestr("knmi.csv", KNMI_CSV)
    return pad


def test_home_ids(dataset_zip):
    with bron_mod.ZipBron(dataset_zip) as b:
        assert b.home_ids() == ["-ORiFQC6", "0RQyG6WX"]


def test_homes_ruw_accepteert_ongedocumenteerde_kolom(dataset_zip):
    # wrong_elec_measurement staat niet in metadata.csv-rijen met document=household.csv, maar
    # moet toch geaccepteerd worden (zie module-docstring afwijking 2), niet als onverwachte kolom.
    with bron_mod.ZipBron(dataset_zip) as b:
        homes = b.homes_ruw()
    assert "wrong_elec_measurement" in homes.columns
    assert len(homes) == 2


def test_lees_domein_filtert_en_hernoemt_heatpump_kolommen(dataset_zip):
    # Kale kolomnamen in het bestand (power/voltage/current/energy) moeten na lezen de
    # gedocumenteerde, geprefixte namen dragen (zie module-docstring afwijking 1).
    with bron_mod.ZipBron(dataset_zip) as b:
        result = b.lees_domein("heatpump.csv", ["-ORiFQC6"], chunksize=1)
    assert list(result["home_id__str"]) == ["-ORiFQC6"]
    assert "heatpump_power" in result.columns
    assert "power" not in result.columns
    assert result["heatpump_power"].iloc[0] == 500.0


def test_lees_domein_leeg_resultaat_bij_onbekende_woning(dataset_zip):
    with bron_mod.ZipBron(dataset_zip) as b:
        result = b.lees_domein("dsmr.csv", ["niet-bestaande-woning"])
    assert result.empty


def test_schema_error_bij_ontbrekende_kolom(dataset_zip, tmp_path):
    kapot = tmp_path / "kapot.zip"
    with zipfile.ZipFile(dataset_zip) as bron_z, zipfile.ZipFile(kapot, "w") as z:
        for naam in bron_z.namelist():
            inhoud = bron_z.read(naam)
            if naam == "dsmr.csv":
                # v_gas_consumed weglaten.
                inhoud = inhoud.replace(b",v_gas_consumed", b"").replace(b",5059.0\n", b"\n").replace(b",100.0\n", b"\n")
            z.writestr(naam, inhoud)

    with bron_mod.ZipBron(kapot) as b:
        with pytest.raises(bron_mod.SchemaError, match="ontbrekend"):
            b.lees_domein("dsmr.csv", ["-ORiFQC6"])


def test_schema_error_bij_onverwachte_kolom(dataset_zip, tmp_path):
    kapot = tmp_path / "kapot.zip"
    with zipfile.ZipFile(dataset_zip) as bron_z, zipfile.ZipFile(kapot, "w") as z:
        for naam in bron_z.namelist():
            inhoud = bron_z.read(naam)
            if naam == "room.csv":
                inhoud = inhoud.replace(b"humidity\n", b"humidity,onbekend_veld\n").replace(
                    b",45.0\n", b",45.0,1\n"
                ).replace(b",50.0\n", b",50.0,1\n")
            z.writestr(naam, inhoud)

    with bron_mod.ZipBron(kapot) as b:
        with pytest.raises(bron_mod.SchemaError, match="onverwacht"):
            b.lees_domein("room.csv", ["-ORiFQC6"])


def test_verdeel_domein_over_chunks_verdeelt_per_woning(dataset_zip):
    # ontwerp: het knelpunt van eenmaal per chunk het hele bestand lezen. Deze methode leest het
    # bestand ÉÉN keer en verdeelt de rijen meteen over de opgegeven chunks.
    with bron_mod.ZipBron(dataset_zip) as b:
        resultaat = dict(b.verdeel_domein_over_chunks("dsmr.csv", {"-ORiFQC6": 0, "0RQyG6WX": 1}))
    assert set(resultaat) == {0, 1}
    assert resultaat[0]["home_id__str"].tolist() == ["-ORiFQC6"]
    assert resultaat[1]["home_id__str"].tolist() == ["0RQyG6WX"]
    # Zelfde kolomhernoeming als lees_domein (heatpump/boiler-namen zijn hier niet van toepassing,
    # maar location_id -> home_id__str wel).
    assert "location_id" not in resultaat[0].columns


def test_verdeel_domein_over_chunks_slaat_woningen_buiten_de_mapping_over(dataset_zip):
    # Een woning die niet in chunk_van_home_id voorkomt (buiten de selectie, of al klaar) wordt
    # overgeslagen -- dat is de optimalisatie bij een hervatte run.
    with bron_mod.ZipBron(dataset_zip) as b:
        resultaat = dict(b.verdeel_domein_over_chunks("dsmr.csv", {"-ORiFQC6": 0}))
    assert set(resultaat) == {0}
    assert len(resultaat[0]) == 1


def test_verdeel_domein_over_chunks_hernoemt_heatpump_kolommen(dataset_zip):
    with bron_mod.ZipBron(dataset_zip) as b:
        resultaat = dict(b.verdeel_domein_over_chunks("heatpump.csv", {"-ORiFQC6": 0}, chunksize=1))
    assert "heatpump_power" in resultaat[0].columns
    assert resultaat[0]["heatpump_power"].iloc[0] == 500.0


def test_lege_domein_frame_heeft_verwachte_kolommen(dataset_zip):
    with bron_mod.ZipBron(dataset_zip) as b:
        leeg = bron_mod.lege_domein_frame("heatpump.csv", b.metadata())
    assert leeg.empty
    assert "heatpump_power" in leeg.columns
    assert "power" not in leeg.columns
