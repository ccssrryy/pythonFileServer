# -*- coding: utf-8 -*-
import os
import socket

import select
import urllib2
from cStringIO import StringIO
from sets import Set

port = 8000
ip = "0.0.0.0"
wlist = Set()
rlist = Set()
socket_handler_dict = dict()  # type:{socket.socket:Handler}


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
    requestLine = ''  # type: str
    _cachedRecvData = ''  # type: str
    _cachedSendData = ''  # type: str
    head_line = ''  # type: str
    header = dict()  # type: dict
    file = None  # type:file
    start = 0  # type:int
    end = -1  # type:int
    size_sent = 0  # type:int

    def onConnectionMade(self):
        print "connection made from ", self.socket.getpeername()

    def onError(self, e):
        print e

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
            self.socket.send("HTTP/1.1 404 Not Found\r\n\r\n<html><title>404</title><body>404 not found</body></html>")
            self.socket.close()
            self.onConnectionLost()
            return
        if os.path.isdir(path):
            folder, subs, fs = os.walk(path).next()
            body = ""
            body += "<html><title>%s</title><body>"%path
            subs.append("..")
            subs.sort()
            for s in subs:
                t = os.path.join(folder, s)
                p = t.split("/")[-1]
                body += "<a href='%s'><i>%s</i></a></br>" % (urllib2.quote(t), p)
            for f in fs:
                t = os.path.join(folder, f)
                p = t.split("/")[-1]
                body += "<a href='%s'><b>%s</b></a></br>" % (urllib2.quote(t), p)
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
        print "connection lost "
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


def main():
    server.bind((ip, port))
    server.setblocking(False)
    server.listen(50)
    rlist.add(server)
    while True:
        rs, ws, xs = select.select(rlist, wlist, [])
        if rs:
            for r in rs:
                if r == server:
                    con, addr = r.accept()
                    print "connected from " + str(con.getpeername())
                    socket_handler_dict[con] = ConnHandler(con)  # type:Handler
                    rlist.add(con)
                    # connection made
                    socket_handler_dict[con].onConnectionMade()
                    continue
                try:
                    data = r.recv(2048)
                    if not data:
                        print "connection lost from ", r.getpeername()
                        rlist.remove(r)
                        # connection lost
                        socket_handler_dict[r].onConnectionLost()
                        continue
                    # process data
                    socket_handler_dict[r].onDataRecv(data)
                except Exception, e:
                    print e
        if ws:
            for w in ws:
                socket_handler_dict[w].onReadyWrite()


if __name__ == "__main__":
    main()
