import pytest
from scraper.validator import (
    calculate_iso6346_check_digit,
    is_valid_container_number,
    is_valid_bol_number,
    detect_shipping_line,
    detect_shipment_type,
)


def test_calculate_iso6346_check_digit():
    # MSCU123456 -> check digit 6
    assert calculate_iso6346_check_digit("MSCU123456") == 6
    # MAEU628492 -> check digit 0
    assert calculate_iso6346_check_digit("MAEU628492") == 0
    # CSQU305438 -> check digit 3
    assert calculate_iso6346_check_digit("CSQU305438") == 3
    # HLXU123456 -> check digit 1
    assert calculate_iso6346_check_digit("HLXU123456") == 1
    # Invalid length
    assert calculate_iso6346_check_digit("SHORT") is None


def test_is_valid_container_number():
    # Valid with correct check digit
    assert is_valid_container_number("MSCU1234566", strict_check_digit=True) is True
    assert is_valid_container_number("MAEU6284920", strict_check_digit=True) is True
    assert is_valid_container_number("CSQU3054383", strict_check_digit=True) is True
    assert is_valid_container_number("HLXU1234561", strict_check_digit=True) is True
    assert is_valid_container_number("mscu 123456 6", strict_check_digit=True) is True

    # Invalid check digit in strict mode
    assert is_valid_container_number("MSCU1234569", strict_check_digit=True) is False
    # Non-strict accepts valid 4-letter + 7-digit pattern
    assert is_valid_container_number("MSCU1234569", strict_check_digit=False) is True

    # Invalid formats
    assert is_valid_container_number("12345678901") is False
    assert is_valid_container_number("INVALID") is False
    assert is_valid_container_number("") is False
    assert is_valid_container_number(None) is False


def test_is_valid_bol_number():
    assert is_valid_bol_number("MSCU12345678") is True
    assert is_valid_bol_number("MEDU987654321") is True
    assert is_valid_bol_number("MAEU1234567890") is True
    assert is_valid_bol_number("SHORT") is False
    assert is_valid_bol_number("12345678") is False  # No letters
    assert is_valid_bol_number("ABCDEFGHIJKL") is False  # No digits


def test_detect_shipping_line():
    assert detect_shipping_line("MSCU1234566") == "msc"
    assert detect_shipping_line("MEDU1234567") == "msc"
    assert detect_shipping_line("MAEU6284920") == "maersk"
    assert detect_shipping_line("MSKU1234567") == "maersk"
    assert detect_shipping_line("CMAU1234567") == "cma_cgm"
    assert detect_shipping_line("COSU1234567") == "cosco"
    assert detect_shipping_line("HLCU1234567") == "hapag_lloyd"
    assert detect_shipping_line("HLXU1234561") == "hapag_lloyd"
    assert detect_shipping_line("ONEU1234567") == "one"
    assert detect_shipping_line("EGLV1234567") == "evergreen"
    assert detect_shipping_line("ZIMU1234567") == "zim"
    assert detect_shipping_line("YMLU1234567") == "yang_ming"
    assert detect_shipping_line("HMMU1234567") == "hmm"
    assert detect_shipping_line("9400100000000000000022") is None


def test_detect_shipment_type():
    assert detect_shipment_type("MSCU1234566") == "ocean_container"
    assert detect_shipment_type("MAEU6284920") == "ocean_container"
    assert detect_shipment_type("9400100000000000000022") == "parcel"
    assert detect_shipment_type("1Z9999999999999999") == "parcel"
    assert detect_shipment_type("123456789012") == "parcel"
