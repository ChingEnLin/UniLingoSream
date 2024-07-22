""" This module is used to setup the logger for the application. 
"""
import logging

def setup_custom_logger(name):
    """ Setup a custom logger with the specified name. """
    formatter = logging.Formatter(fmt='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    return logger
