# -*- coding: utf-8 -*-
"""
Created on 2026-06-18T20:37:13-04:00

@author: nate
"""
import argh
from loguru import logger

import nate_e2a


def main():
    logger.info(__name__)

def cli():
    parser = argh.ArghParser()
    parser.add_commands([
            main
    ])
    parser.dispatch()

    # Only one entrypoint
    #argh.dispatch_command(main)