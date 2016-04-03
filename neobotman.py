
import os, sys, time, random
import apsw
import irc.bot
import unicodedata

DBFILENAME='neobotman.sqlite'
MAX_SENTENCE = 120

def dbinit(connection):
	connection.cursor().execute("create table settings(skey text primary key not null, sval text); \
					create table words(word text primary key not null); \
					create table seqs(prevword int, nextword int, occurences int default 0, primary key(prevword, nextword));")

class SettingGroup:
	def __init__(self, connection):
		self.c = connection
		self.s = {}
		self.retrieve()
	def retrieve(self):
		self.s = {}
		kvpairs = self.c.cursor().execute("select skey, sval from settings")
		for i in kvpairs:
			self.s[str(i[0])] = i[1]
	def __getitem__(self, item):
		return self.s[item]
	def __setitem__(self, key, value):
		self.c.cursor().execute("insert or replace into settings(skey, sval) values(?, ?)", (key, value))
		self.s[key] = value

class NeoBotman(irc.bot.SingleServerIRCBot):
	def __init__(self, settings, connection):
		self.settings = settings
		self.dbc = connection
		self.sr = random.SystemRandom()
		irc.bot.SingleServerIRCBot.__init__(self, [(self.settings['server'], int(self.settings['port']))], self.settings['nick'], self.settings['nick'])
	
	def on_nicknameinuse(self, c, e):
		c.nick(self.settings['nick2'])
	def on_welcome(self, c, e):
		c.join(self.settings['channel'])
	def on_pubmsg(self, c, e):
		msg = e.arguments[0]
		if msg[0] == '!':
			if msg[1:] == 'phrase':
				self.sendnewsentence(c)
		else:
			self.readstring(msg)
			if str(c.get_nickname()).lower() in str(msg).lower():
				self.sendnewsentence(c)
	def sendnewsentence(self, c):
			sentence = self.generatestring()
			c.privmsg(self.settings['channel'], sentence)
	def readstring(self, string):
		cursor = self.dbc.cursor()
		rawwords = string.split(' ')
		rwbindings = []
		for rw in rawwords:
			rwbindings.append((rw, rw))
		idresults = cursor.executemany("insert or ignore into words(word) values(?); select rowid from words where word = ?;", (rwbindings))
		# For each word we add an occurence with the preceding word
		updatequery = "insert or replace into seqs(prevword, nextword) values(?, ?); update seqs set occurences = occurences + 1 where prevword = ? and nextword = ?"
		preceding = -1
		for wid in idresults:
			wordid = wid[0]
			self.dbc.cursor().execute(updatequery, (preceding, wordid, preceding, wordid))
			preceding = wordid
		# Then we add the sentence ending occurence (-1)
		cursor.execute(updatequery, (preceding, -1, preceding, -1))
	def generatestring(self):
		sentence = ''
		wid = -1
		finished = False
		while not finished:
			nwresults = self.dbc.cursor().execute("select nextword, occurences from seqs where prevword = ?;", (wid,))
			nwchoices = []
			totaloccurences = 0
			for nwid, occurences in nwresults:
				nextword = None
				if nwid >= 0:
					nwres = self.dbc.cursor().execute("select word from words where rowid = ?", (nwid,)).fetchone()
					if nwres:
						nextword = str(nwres[0])
				nwchoices.append((nextword, occurences, nwid))
				totaloccurences += occurences
			# Weighted random for actually picking the next word
			word = None
			while not word:
				randomnumber = self.sr.randint(0, totaloccurences - 1)
				noccurences = 0
				for choice in nwchoices:
					noccurences += choice[1]
					if noccurences > randomnumber:
						word = choice
						break
			# Adding the word to the sentence
			wid = word[2]
			if wid >= 0:
				if len(sentence) > 0:
					sentence += ' '
				sentence += word[0]
				if len(sentence) > MAX_SENTENCE:
					finished = True
			else:
				finished = True
		return sentence

irc.client.ServerConnection.buffer_class = irc.buffer.LenientDecodingLineBuffer

if len(sys.argv) > 1 and sys.argv[1] == 'init':
	if os.path.exists(DBFILENAME):
		os.remove(DBFILENAME)
	connection=apsw.Connection(DBFILENAME)
	dbinit(connection)
	settings = SettingGroup(connection)
	print('IRC server:')
	settings['server'] = input('> ').strip()
	print('Port: (if empty, 6667)')
	port = input('> ').strip()
	if port == '':
		settings['port'] = 6667
	else:
		settings['port'] = port
	print('Nickname:')
	settings['nick'] = input('> ').strip()
	settings['nick2'] = settings['nick'] + '_'
	print('Channel:')
	settings['channel'] = input('> ').strip()
else:
	connection=apsw.Connection(DBFILENAME)
	settings = SettingGroup(connection)
nbm = NeoBotman(settings, connection)
nbm.start()
connection.close()
