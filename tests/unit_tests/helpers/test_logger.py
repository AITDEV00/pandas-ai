import logging

import pytest

from pandasai.helpers.logger import Logger


@pytest.fixture(autouse=True)
def _clear_logger_handlers():
    """Clear the singleton logger's handlers before each test to avoid cross-test pollution."""
    _logger = logging.getLogger("pandasai.helpers.logger")
    _logger.handlers.clear()
    yield
    _logger.handlers.clear()


def test_verbose_setter():
    # Initialize logger with verbose=False, save_logs=False
    logger = Logger(verbose=False, save_logs=False)
    assert logger._verbose is False
    assert not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger._logger.handlers
    )

    # Set verbose to True
    logger.verbose = True
    assert logger._verbose is True
    assert any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger._logger.handlers
    )
    assert len(logger._logger.handlers) == 1

    # Set verbose to False
    logger.verbose = False
    assert logger._verbose is False
    assert not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger._logger.handlers
    )
    assert len(logger._logger.handlers) == 0

    # Set verbose to True again to ensure multiple toggles work
    logger.verbose = True
    assert logger._verbose is True
    assert any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger._logger.handlers
    )
    assert len(logger._logger.handlers) == 1


def test_save_logs_property():
    # Initialize logger with save_logs=False, verbose=False
    logger = Logger(save_logs=False, verbose=False)
    assert logger.save_logs is False

    # Enable save_logs
    logger.save_logs = True
    assert logger.save_logs is True
    assert any(
        isinstance(handler, logging.FileHandler) for handler in logger._logger.handlers
    )

    # Disable save_logs
    logger.save_logs = False
    assert logger.save_logs is False
    assert not any(
        isinstance(handler, logging.FileHandler) for handler in logger._logger.handlers
    )


def test_save_logs_property_defaults_with_save_logs():
    # When logger is initialized with save_logs=True (default), it should have a FileHandler
    logger = Logger(save_logs=True)
    assert logger.save_logs is True


def test_save_logs_property_defaults_verbose_only():
    # When logger is initialized with save_logs=False but verbose=True,
    # save_logs should be False (no FileHandler), but verbose output is enabled
    logger = Logger(save_logs=False, verbose=True)
    assert logger.save_logs is False
    assert logger.verbose is True


def test_save_logs_property_defaults_no_handlers():
    # When both save_logs and verbose are False, there should be no handlers
    logger = Logger(save_logs=False, verbose=False)
    assert logger.save_logs is False
