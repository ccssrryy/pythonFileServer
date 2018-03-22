# -*- coding: utf-8 -*-
import argparse
import mimetypes
import os
import socket
import base64
import select
import urllib2
from cStringIO import StringIO
from sets import Set
import signal
import logging

parser = argparse.ArgumentParser()
parser.add_argument('-p', '--port', help='port number', type=int, default=8000)
parser.add_argument('-d', '--dir', help='work dir', type=str, default='./')
parser.add_argument('-l ', '--loglevel', help='log level', type=str, default='DEBUG')
parser.add_argument('-u', '--user', help='username', type=str, default='admin')
parser.add_argument('-k', '--key', help='key', type=str, default='admin')
args = parser.parse_args()
user = args.user
key = args.key
port = args.port
os.chdir(args.dir)
ip = "0.0.0.0"
wlist = Set()
rlist = Set()
socket_handler_dict = dict()  # type:{socket.socket:Handler}
logging.basicConfig(level=getattr(logging, args.loglevel),
                    format="%(asctime)s - [%(levelname)s]: %(message)s")
_logger = logging.getLogger()

class Handler(object):
    def __init__(self, soc):
        self.socket = soc  # type:socket.socket

    def onConnectionMade(self):
        raise NotImplementedError()

    def onConnectionLost(self):
        raise NotImplementedError()

    def onDataRecv(self, data):
        raise NotImplementedError()

    def onError(self, e):
        raise NotImplementedError()


class ConnHandler(Handler, object):
    def __init__(self,soc):
        super(ConnHandler,self).__init__(soc)
        self.requestLine = ''  # type: str
        self._cachedRecvData = ''  # type: str
        self._cachedSendData = ''  # type: str
        self.head_line = ''  # type: str
        self.header = dict()  # type: dict
        self.file = None  # type:file
        self.start = 0  # type:int
        self.end = -1  # type:int
        self.size_sent = 0  # type:int
        self.peername = ()

    def onConnectionMade(self):
        _logger.debug("connection made from %s", self.socket.getpeername())
        self.peername = self.socket.getpeername()

    def onError(self, e):
        _logger.debug(e)

    def onDataRecv(self, data):
        if len(self._cachedRecvData) > 2048:
            self.socket.send("HTTP/1.1 405 forbidden\r\n\r\nforbidden,header is too long")
            self.socket.close()
            self.onConnectionLost()
            return
        self._cachedRecvData += data
        index = self._cachedRecvData.find("\r\n\r\n")
        if index != -1:
            self.requestLine = self._cachedRecvData[:index]
            self._cachedRecvData = ''
            rlist.remove(self.socket)
        else:
            return
        c = StringIO(self.requestLine)  # type:StringIO
        self.head_line = c.readline()
        for l in c.readlines():
            k, v = l.split(":", 1)  # type: str
            self.header[k.strip()] = v.strip()
        if self.header.has_key("Authorization"):
            t = self.header.get("Authorization").split(" ")
            method = t[0]
            k = t[1]
            k = base64.b64decode(k).split(":")
            if k[0] != user or k[1] != key:
                self.socket.send("HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic\r\n\r\n")
                return
        else:
            self.socket.send("HTTP/1.1 401 Authorization Required\r\nWWW-Authenticate: Basic\r\n\r\n")
            return
        if not self.head_line.startswith("GET"):
            self.socket.send("HTTP/1.1 405 forbidden\r\n\r\nsorrys!request method is not supported!")
            self.socket.close()
            self.onConnectionLost()
            return
        path = "." + self.head_line.split(" ")[1]
        path=urllib2.unquote(path)
        if not os.path.realpath(path).startswith(os.path.realpath("./")):
            self.socket.send("HTTP/1.1 405 forbidden\r\n\r\nsorrys!you have no permission to access the file path!")
            self.socket.close()
            self.onConnectionLost()
            return
        if not os.path.exists(path):
            self.socket.send("HTTP/1.1 404 Not Found\r\n\r\n<html><title>404</title><body>404 not found:%s</body></html>"%path)
            self.socket.close()
            self.onConnectionLost()
            return
        if os.path.isdir(path):
            folder, subs, fs = os.walk(path).next()
            body = ""
            body += "<html>" \
                    "<title>%s</title>" \
                    "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\" />" \
                    "<body>" % path
            subs.append("..")
            subs.sort()
            fs.sort()
            for s in subs:
                t = os.path.join(folder, s)
                p = t.split("/")[-1]
                body += "<a href='%s'><i>%s</i></a></br>" % (urllib2.quote(t)[1:], p)
            for f in fs:
                t = os.path.join(folder, f)
                p = t.split("/")[-1]
                mim=mimetypes.guess_type(p)[0]
                if False:#mim.find("video")!=-1:
                    body+="<h3>%s</h3><video title='%s' controls ><source src=\"%s\" type=\"%s\"></video></br>"%(p,p,urllib2.quote(t),mim)
                else:
                    body += "<a href='%s'><b>%s</b><i>(%s)</i></a></br>" % (urllib2.quote(t)[1:], p,m_size(os.path.getsize(t)))
            body += "</body></html>"
            self.socket.send("HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
            self.socket.close()
            self.onConnectionLost()
            return

        ran = self.header.get("Range", None)
        if ran:
            ran = ran[6:]
            t1 = ran.split("-")
            self.start = int(t1[0])
            if t1[1]:
                self.end = int(t1[1])
            else:
                self.end = os.path.getsize(path) - 1
            self._cachedSendData = "HTTP/1.1 206 Partial Content\r\nContent-Length: %d\r\nContent-Range: bytes " \
                                   "%d-%d/%d\r\n" \
                                   "Accept-Ranges: bytes\r\n\r\n" % (self.end - self.start + 1,self.start,self.end, os.path.getsize(path))
        else:
            self._cachedSendData = "HTTP/1.1 200 OK\r\nAccept-Ranges: bytes\r\nContent-Length: %d\r\n\r\n" % os.path.getsize(
                path)
        self.file = open(path, "r")
        self.file.seek(self.start)
        wlist.add(self.socket)

    def onConnectionLost(self):
        if self.file:
            self.file.close()
        _logger.debug("connection lost %s",self.peername)
        try:
            wlist.remove(self.socket)
        except:
            pass
        try:
            rlist.remove(self.socket)
        except:
            pass

    def onReadyWrite(self):
        if self._cachedSendData:
            size = self.socket.send(self._cachedSendData)
            l = len(self._cachedSendData)
            self._cachedSendData = self._cachedSendData[size:]
            if size != l:
                return
        if self.end==-1:
            c=self.file.read(2048)
        else:
            more = self.end - self.start + 1 - self.size_sent
            c = self.file.read(min(2048, more))
        if not c:
            self.socket.close()
            self.onConnectionLost()
            return
        try:
            size = self.socket.send(c)
        except:
            self.onConnectionLost()
            return
        self.size_sent += size
        if size != len(c):
            self.file.seek(self.file.tell() - (len(c) - size))


server = socket.socket()
def close_server(*args):
    server.close()
    _logger.debug("server closed")

def init_signal():
    signal.signal(signal.SIGINT, close_server)

def main():
    init_signal()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ip, port))
    server.setblocking(False)
    server.listen(5)
    rlist.add(server)
    while True:
        rs, ws, xs = select.select(rlist, wlist, [])
        if rs:
            for r in rs:
                if r == server:
                    con, addr = r.accept()
                    socket_handler_dict[con] = ConnHandler(con)  # type:Handler
                    rlist.add(con)
                    # connection made
                    socket_handler_dict[con].onConnectionMade()
                    continue
                try:
                    data = r.recv(2048)
                    if not data:
                        rlist.remove(r)
                        # connection lost
                        socket_handler_dict[r].onConnectionLost()
                        _logger.debug("connection lost from peer %s", r.peername)
                        continue
                    # process data
                    socket_handler_dict[r].onDataRecv(data)
                except Exception as e:
                    _logger.debug(e.args)
        if ws:
            for w in ws:
                socket_handler_dict[w].onReadyWrite()


def m_size(size):
    a = ['b', 'k', 'm', 'g']
    if size == 0:
        return '0b'
    r = ''
    for i in range(0,4):
        e = size % 1024
        r = str(e) + a[i] + r
        size >>= 10
        if size == 0:
            break
    return r

if __name__ == "__main__":
    main()
