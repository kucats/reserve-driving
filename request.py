#!/usr/bin/env python

import click
from logging import getLogger
import logging.config
import traceback

from parser import *

logger = getLogger(__name__)
logging.basicConfig(filename='/tmp/drv_request.log',level=logging.DEBUG)

ks = Kyoshu()

def main():
	cmd()

@click.group()
def cmd():
	pass

@cmd.command()
@click.option('--month','-m',required=True)
@click.option('--day','-d',required=True)
@click.option('--hour','-h',required=True)
def do_reserve(month,day,hour):
    print('do_reserve')
    ks.do_reserve(month,day,hour)

@cmd.command()
@click.option('--month','-m',required=True)
@click.option('--day','-d',required=True)
@click.option('--hour','-h',required=True)
def regist_reserve(month,day,hour):
    ks.add_new_reserve(month,day,hour)

@cmd.command()
@click.option('--month','-m',required=True)
@click.option('--day','-d',required=True)
@click.option('--hour','-h',required=True)
def delete_reserve(month,day,hour):
    ks.del_reserve(month,day,hour)

@cmd.command()
@click.option('--month','-m',required=True)
@click.option('--day','-d',required=True)
@click.option('--hour','-h',required=True)
def check_and_do_reserve(month,day,hour):
    ks.check_and_do_reserve(month,day,hour)



if __name__ == '__main__':
	logger.info('start')
	try:
		main()
	except:
		logger.error(traceback.format_exc())
	logger.info('End')
