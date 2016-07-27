#!/usr/bin/env/python

import lxml.html
import requests

import os.path

import slackweb

from lxml import html

from urllib.parse import urlparse, parse_qs

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

	def _notify(self,text):
		self.slack.notify(text=text)

	def _filter_operations_by_name(self,name):
		operations=self.operations
		for ops in operations:
			if ops['action_ja'] == '技能予約':
				url=ops['url']
				return self.url_base+url
		return False

	def _filter_string_by_date(self,string,month,day):
		if month+'月' in string and day+'日' in string:
			return True

	def _filter_dom_by_date(self,doms,month,day):
		for dom in doms:
			if self._filter_string_by_date(dom.text,month,day):
				return dom
		return False

	def do_reserve(self,month,day,hour):
		#特定の時限の予約を行う
		g = self.get_reserve_page(month,day)
		for each in g:
			each_hour = each.get('hour',{})
			each_url = each.get('url',{})
			if hour==each_hour:
				url=each_url
				break
		if url is False:
			return False

		r = self.session_requests.get(url)
		r.encoding='Shift_JIS'

		#指名があれば

		#指名がなければ
		dom = html.fromstring(r.text.strip())
		form_dom=dom.xpath('//form')[0]

		action = form_dom.action

		input_dom=dom.xpath('//form/input')
		payload = {}

		#hidden パラメータを読み込んで送るようにする
		for dom in input_dom:
			if 'b.' in dom.name or 'token' in dom.name or 'struts.token.name' in dom.name:
				payload[dom.name] = dom.value

		payload['method:doYes'] = 1

		r = self.session_requests.post(
			self.url_base+action,
			data = payload
		)
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip().replace('BR', '').replace('br', ''))
		#fetch error
		font_dom_ok=dom.xpath("//font[@class='ok']")
		font_dom_error=dom.xpath("//font[@class='error']")
		if len(font_dom_ok) != 0 and font_dom_ok[0].text is not False:
			self._notify('予約成功: ('+month+'/'+day+' '+hour+'限) を予約しました')
		elif len(font_dom_error) != 0 and font_dom_error[0].text is not False:
			self._notify('予約エラー: ('+month+'/'+day+' '+hour+'限) '+font_dom_error[0].text)
		else:
			self._notify('例外発生: ('+month+'/'+day+' '+hour+'限) 予約のステータスを確認してください')



	def get_reserve_page(self,month,day):
		#その日にちの予約URL一覧を取得
		r = self.session_requests.get(self._filter_operations_by_name('技能予約'))
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')
		dom = self._filter_dom_by_date(link_doms,month,day)

		#日付ごとの予約ページを取得する
		r = self.session_requests.get(self.url_base+dom.attrib['href'])
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')
		list=[]
		for dom in link_doms:
			b={}
			#時間指定のものを抜く
			if '○' in dom.text or '×' in dom.text or 'Ｓ' in dom.text:
				u= parse_qs(urlparse(self.url_base+dom.attrib['href']).query)
				b['hour']=u.get('b.infoPeriodNumber', [''])[0]
				b['url']=self.url_base+dom.attrib['href']
				list.append(b)
		return list


	def get_page_reservation(self):
		url=self._filter_operations_by_name('技能予約')
		r = self.session_requests.get(url)
		r.encoding='Shift_JIS'
		dom = html.fromstring(r.text.strip())
		link_doms=dom.xpath('//a')

		#next week
		for dom in link_doms:
			if '前週' in dom.text:
				prev=self.url_base+dom.attrib['href']
			elif '次週' in dom.text:
				next=self.url_base+dom.attrib['href']
		list=[]

		for u in [url,next]:
			r = self.session_requests.get(u)
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
					if(hours['description']=='Available' or hours['description']=='Available[S]'):
						self._notify('[空き]'+date+' '+str(hours['hour'])+'限の予約ができるようになりました (state has changed from '+saved_hours['description']+' to '+hours['description']+')')
					elif(hours['description']=='Unavailable'):
						self._notify(date+' '+str(hours['hour'])+'限は、予約されてしまいました。 (state has changed from '+saved_hours['description']+' to '+hours['description']+')')
					else:
						self._notify('Date: '+date+' Hour:'+str(hours['hour'])+' state has changed from '+saved_hours['description']+' to '+hours['description'])

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
	#Kyoshu.do_reserve('7','29','9')

if __name__ == '__main__':
	main()
