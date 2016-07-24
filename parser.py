#!/usr/bin/env/python

import lxml.html
import requests

from lxml import html

import configparser

class Kyoshu(object):

	def __init__(self):
		inifile = configparser.SafeConfigParser()
		inifile.read('./config.ini')

		self.m_user=inifile.get('identifier','user_no')
		self.m_passwd=inifile.get('identifier','user_password')
		#m_base_url=inifile.get('greserve','mobile_url')
		self.url_base=inifile.get('greserve','url_base')
		self.url_login=inifile.get('greserve','url_login')
		self.m_base_url=inifile.get('greserve','mobile_url')
		self.session_requests = requests.session()
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
		for dom in link_doms:
			b={}
			b['date']=dom.text
			b['resinfo']=str(dom.getnext().tail).strip().replace(' ','')
			b['schedule']=self._convert_schedule_string_to_obj(b['resinfo'])

			if '月' in b['date'] and '日' in b['date']:
				list.append(b)

		return list

	def _convert_schedule_string_to_obj(self,string):
		strlist=[]
		strlist=list(str(string))
		schedule_list=[]
		desc=''
		h=1
		for m in strlist:
			d={}
			if m=='X':
				desc='Unavailable'
			elif m=='J':
				desc='Reserved'
			elif m=='O':
				desc='Available'
			elif m=='-':
				desc='Offline'
			elif m=='K':
				desc='Test'
			elif m=='G':
				desc='Desk Reserved'

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
