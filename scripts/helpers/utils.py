import re

from telegram.ext import ContextTypes

from extensions.extension_base import ExtensionBase


def validate_address(address: str) -> bool:
    """
    Validate address.
    :return: True if address is valid according to eth standard, False otherwise.
    """
    regex = re.compile("0x[0-9a-fA-F]{40}\Z", re.I)
    return regex.match(address)


def remove_job_if_exists(context: ContextTypes.DEFAULT_TYPE, job_name: str) -> bool:
    """
    Remove telegram bot job.
    :return: True if job was found and removed, False otherwise.
    """
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def get_extension_by_name(ext_name: str) -> ExtensionBase:
    ext_module = getattr(__import__(f"extensions.{ext_name}"), ext_name)
    return getattr(ext_module, ext_name.capitalize())
