"""
Useful utility functions.
"""
import re

from telegram.ext import ContextTypes

from extensions.extension_base import ExtensionBase


def validate_address(address: str) -> bool:
    """
    Validate address.
    :param address: eth address to check.
    :return: True if address is valid according to eth standard, False otherwise.
    """
    regex = re.compile("0x[0-9a-fA-F]{40}\Z", re.I)
    return regex.match(address)


def validate_name(name: str) -> bool:
    """
    Validate name identifier.
    :param address: name string to check.
    :return: True if name identifier is valid, False otherwise.
    """
    if len(name) > 100 or len(name) == 0:
        return False
    return True


def validate_url(url: str) -> bool:
    """
    Validate url.
    :param address: url string to check.
    :return: True if url is valid, False otherwise.
    """
    if len(url) == 0:
        return False
    return True


def job_exist(context: ContextTypes.DEFAULT_TYPE, job_name: str) -> bool:
    """
    Check if job exists.
    :param job_name: job identifier to check.
    :return: True if job was found, False otherwise.
    """
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        return False
    return True


def remove_job_if_exists(context: ContextTypes.DEFAULT_TYPE, job_name: str) -> bool:
    """
    Remove telegram bot job.
    :param job_name: job identifier to check.
    :return: True if job was found and removed, False otherwise.
    """
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def get_extension_by_name(ext_name: str) -> ExtensionBase:
    """
    Load extension module.
    :param ext_name: the name of the extension to load (e.g. "forta").
    :return: the extension instance if successful, throws exception otherwise.
    """
    ext_module = getattr(__import__(f"extensions.{ext_name}"), ext_name)
    return getattr(ext_module, ext_name.capitalize())
