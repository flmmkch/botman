#!/usr/bin/python3

import os, sys, time, random
import apsw
import irc, irc.bot
import unicodedata
from botman import SettingGroup, BotmanCore, BotmanInterface

class IRCBotman(BotmanInterface):
	COMMAND_SIGN = '!'
	def __init__(self, handler):
		super().__init__()
		self.handler = handler
	def configure(self):
		super().configure()
		print('IRC server:')
		self.settings['irc_server'] = input('> ').strip()
		print('Port: (if empty, 6667)')
		port = input('> ').strip()
		if port == '':
			self.settings['irc_port'] = 6667
		else:
			self.settings['irc_port'] = port
		print('Nickname:')
		self.settings['irc_nick'] = input('> ').strip()
		self.settings['irc_nick2'] = self.settings['irc_nick'] + '_'
		print('Channel:')
		self.settings['irc_channel'] = input('> ').strip()
	def sendnewsentence(self, target, base = '', invert = False, userparams = None):
		sentence = super().sendnewsentence(target, base, invert, userparams)
		self.handler.send(userparams['c'], sentence.replace("\r","").replace("\n",""), target)

class IRCBotmanHandler(irc.bot.SingleServerIRCBot):
	def __init__(self):
		self.botman = IRCBotman(self)
		self.settings = self.botman.settings
		irc.bot.SingleServerIRCBot.__init__(self, [(self.settings['irc_server'], int(self.settings['irc_port']))], self.settings['irc_nick'], self.settings['irc_nick'])
	def on_nicknameinuse(self, c, e):
		c.nick(self.settings['irc_nick2'])
	def on_welcome(self, c, e):
		c.join(self.settings['irc_channel'])
	def on_pubmsg(self, c, e):
		self.receive(c, e, e.target)
	def on_privmsg(self, c, e):
		self.receive(c, e, e.source[:e.source.find('!')])
	def on_join(self, c, e):
		print('Joining channel', e.target)
	def receive(self, c, e, target):
		nick = c.get_nickname().lower()
		if not c.get_nickname() in self.botman.aliases:
			self.botman.aliases.append(nick)
		self.botman.receivemessage(e.arguments[0], target, {'c': c})
	def on_kick(self, c, e):
		if e.target == self.settings['irc_channel'] and e.arguments[0] == c.get_nickname():
			c.join(self.settings['irc_channel'])
	def send(self, c, sentence, target):
		c.privmsg(target, sentence)

irc.client.ServerConnection.buffer_class = irc.buffer.LenientDecodingLineBuffer

botman = IRCBotmanHandler()
botman.start()
