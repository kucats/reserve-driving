#!/usr/bin/env/python

import lxml.html
import requests

import os.path

import slackweb

from lxml import html

import configparser
import json

class Kyoshu(object):

	def __init__(self):
		inifile = configparser.SafeConfigParser()
		inifile.read('./config.ini')

		self.m_user=inifile.get('identifier','user_no')
		self.m_passwd=inifile.get('identifier','user_password')
		self.url_base=inifile.get('greserve','url_base')
		self.url_login=inifile.get('greserve','url_login')
		self.m_base_url=inifile.get('greserve','mobile_url')
		self.file_schedule_all=inifile.get('file','schedule_all')

		self.slack_integration=inifile.get('greserve','slack_integration')

		self.session_requests = requests.session()
		self.slack = slackweb.Slack(url=self.slack_integration)

		self.do_login()

	def do_login(self):
		r = self.session_requests.get(self.m_base_url)
		payload = {
			"b.schoolCd" : "xaFIWet1fi0+brGQYS+1OA==",
			"server" : "el25aspa",
			"b.studentId" : self.m_user,
			"b.password" : self.m_passwd,
			"method:doLogin" : '1'
		}
		result = self.session_requests.post(
			self.url_login,
			data = payload,
			headers = dict(referer=self.m_base_url))
		result.encoding = 'Shift_JIS'
		dom = html.fromstring(result.text)
		link_doms=dom.xpath('//a')

		operations=[]
		for dom in link_doms:
			b={}
			b['action_ja']=dom.text
			b['url']=dom.attrib['href']
			operations.append(b)
		self.operations=operations

	def get_page_reservation(self):
		operations=self.operations

		for ops in operations:
			if ops['action_ja'] == '技能予約':
				url=ops['url']
		r = self.session_requests.get(self.url_base+url)
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')

		#next week
		for dom in link_doms:
			if '前週' in dom.text:
				prev=dom.attrib['href']
			elif '次週' in dom.text:
				next=dom.attrib['href']
		list=[]

		for u in [url,next]:
			r = self.session_requests.get(self.url_base+u)
			r.encoding='Shift_JIS'
			dom = html.fromstring(r.text.strip())
			link_doms=dom.xpath('//a')

			for dom in link_doms:
				b={}
				b['date']=dom.text
				b['resinfo']=str(dom.getnext().tail).strip().replace(' ','')
				b['schedule']=self._convert_schedule_string_to_obj(b['resinfo'])

				if '月' in b['date'] and '日' in b['date']:
					list.append(b)

		self._compare_schedule(list)
		self._save_schedule_to_file(list)
		return list

	def _compare_schedule(self,dict):
		saved_dict = self._open_schedule_from_file()
		if saved_dict == False:
			return False

		while (saved_dict[0]['date'] != dict[0]['date']):
			saved_dict.pop(0)

		for saved_date_dict,date_dict in zip(saved_dict,dict):
			date=date_dict['date']
			print('check for '+date)
			for saved_hours,hours in zip(saved_date_dict['schedule'],date_dict['schedule']):
				if saved_hours['description'] != hours['description']:
					if(hours['description']=='Available'):
						self.slack.notify(text=date+' '+hours['hour']+'限の予約ができるようになりました (state changed from '+saved_hours['description']+' to '+hours['description']+')')
					else:
						self.slack.notify(text='Date: '+date+' Hour:'+str(hours['hour'])+' state is changed from '+saved_hours['description']+' to '+hours['description'])

	def _save_schedule_to_file(self,dict):
		with open(self.file_schedule_all,'w') as f:
			json.dump(dict, f, sort_keys=True, indent=4)

	def _open_schedule_from_file(self):
		if (os.path.exists(self.file_schedule_all)==False):
			return False

		with open(self.file_schedule_all,'r') as f:
			return json.load(f)

	def _convert_schedule_string_to_obj(self,string):
		strlist=[]
		strlist=list(str(string))
		schedule_list=[]
		desc=''
		h=1
		for m in strlist:
			d={}
			if m=='X':
				#枠はあるが、予約で一杯
				desc='Unavailable'
			elif m=='J':
				#予約済み
				desc='Reserved'
			elif m=='O':
				#予約可能
				desc='Available'
			elif m=='-':
				#そもそも枠がない
				desc='Unavailable'
			elif m=='K':
				#検定予約済み
				desc='Test'
			elif m=='G':
				desc='Desk Reserved'
			elif m=='S':
				#指名予約可
				desc='Available[S]'

			d['hour']=h
			d['str']=m
			d['description']=desc

			schedule_list.append(d)
			h=h+1
		return schedule_list


Kyoshu = Kyoshu()

def main():
	Kyoshu.get_page_reservation()

if __name__ == '__main__':
	main()
