import os
import smtplib
from email.mime.text import MIMEText
from typing import Literal

from curl_cffi import requests as curl_requests


class NotificationKit:
	@property
	def email_user(self) -> str:
		return os.getenv('EMAIL_USER', '')

	@property
	def email_pass(self) -> str:
		return os.getenv('EMAIL_PASS', '')

	@property
	def email_to(self) -> str:
		return os.getenv('EMAIL_TO', '')

	@property
	def smtp_server(self) -> str:
		return os.getenv('CUSTOM_SMTP_SERVER', '')

	@property
	def pushplus_token(self):
		return os.getenv('PUSHPLUS_TOKEN')

	@property
	def server_push_key(self):
		return os.getenv('SERVERPUSHKEY')

	@property
	def dingding_webhook(self):
		return os.getenv('DINGDING_WEBHOOK')

	@property
	def feishu_webhook(self):
		return os.getenv('FEISHU_WEBHOOK')

	@property
	def weixin_webhook(self):
		return os.getenv('WEIXIN_WEBHOOK')

	@property
	def telegram_bot_token(self):
		return os.getenv('TELEGRAM_BOT_TOKEN')

	@property
	def telegram_chat_id(self):
		return os.getenv('TELEGRAM_CHAT_ID')

	def send_email(self, title: str, content: str, msg_type: Literal['text', 'html'] = 'text'):
		if not self.email_user or not self.email_pass or not self.email_to:
			raise ValueError('Email configuration not set')

		# MIMEText 需要 'plain' 或 'html'，而不是 'text'
		mime_subtype = 'plain' if msg_type == 'text' else 'html'
		msg = MIMEText(content, mime_subtype, 'utf-8')
		msg['From'] = f'newapi.ai Assistant <{self.email_user}>'
		msg['To'] = self.email_to
		msg['Subject'] = title

		smtp_server = self.smtp_server if self.smtp_server else f'smtp.{self.email_user.split("@")[1]}'
		with smtplib.SMTP_SSL(smtp_server, 465) as server:
			server.login(self.email_user, self.email_pass)
			server.send_message(msg)

	def send_pushplus(self, title: str, content: str):
		if not self.pushplus_token:
			raise ValueError('PushPlus Token not configured')

		data = {'token': self.pushplus_token, 'title': title, 'content': content, 'template': 'html'}
		curl_requests.post('http://www.pushplus.plus/send', json=data, timeout=30)

	def send_serverPush(self, title: str, content: str):
		if not self.server_push_key:
			raise ValueError('Server Push key not configured')

		data = {'title': title, 'desp': content}
		curl_requests.post(f'https://sctapi.ftqq.com/{self.server_push_key}.send', json=data, timeout=30)

	def send_dingtalk(self, title: str, content: str):
		if not self.dingding_webhook:
			raise ValueError('DingTalk Webhook not configured')

		data = {'msgtype': 'text', 'text': {'content': f'{title}\n{content}'}}
		curl_requests.post(self.dingding_webhook, json=data, timeout=30)

	def send_feishu(self, title: str, content: str):
		if not self.feishu_webhook:
			raise ValueError('Feishu Webhook not configured')

		data = {
			'msg_type': 'interactive',
			'card': {
				'elements': [{'tag': 'markdown', 'content': content, 'text_align': 'left'}],
				'header': {'template': 'blue', 'title': {'content': title, 'tag': 'plain_text'}},
			},
		}
		curl_requests.post(self.feishu_webhook, json=data, timeout=30)

	def send_wecom(self, title: str, content: str):
		if not self.weixin_webhook:
			raise ValueError('WeChat Work Webhook not configured')

		data = {'msgtype': 'text', 'text': {'content': f'{title}\n{content}'}}
		curl_requests.post(self.weixin_webhook, json=data, timeout=30)

	def send_telegram(self, title: str, content: str):
		if not self.telegram_bot_token or not self.telegram_chat_id:
			raise ValueError('Telegram Bot Token or Chat ID not configured')

		text = f'*{title}*\n{content}'
		data = {'chat_id': self.telegram_chat_id, 'text': text, 'parse_mode': 'Markdown'}
		curl_requests.post(f'https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage', json=data, timeout=30)

	def push_message(self, title: str, content: str, msg_type: Literal['text', 'html'] = 'text'):
		notifications = [
			('Email', lambda: self.send_email(title, content, msg_type)),
			('PushPlus', lambda: self.send_pushplus(title, content)),
			('Server Push', lambda: self.send_serverPush(title, content)),
			('DingTalk', lambda: self.send_dingtalk(title, content)),
			('Feishu', lambda: self.send_feishu(title, content)),
			('WeChat Work', lambda: self.send_wecom(title, content)),
			('Telegram', lambda: self.send_telegram(title, content)),
		]

		for name, func in notifications:
			try:
				func()
				print(f'🔹 [{name}]: Message push successful!')
			except Exception as e:
				print(f'🔸 [{name}]: Message push failed! Reason: {str(e)}')


notify = NotificationKit()
