# -*- coding: utf-8 -*-

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtXml import *

from ShellProcess import *
from time import *
from functools import *

## Container for service definitions and state polling.
# This class manages a list of processes which perform install/running checks and
# it can be set up to monitor its own state. When the state changes, the stateChanged()
# signal is emitted.
class Service(QObject):


  def __init__(self, parent = None):
    QObject.__init__(self, parent)
    self.parent = self.source = parent

    self.id = ''
    self.name = ''
    self.priority = 0
    self.description = ''
    self.installCheck = ''
    self.runningCheck = ''
    self.startCommand = ''
    self.stopCommand = ''
    self.processes = set()
    self.environment = None
    self.sleepTime = 0
    self.state = ('unknown', 'unknown')   # (Install-Status, Running-Status)

    # Timer einrichten und connecten (gestartet wird er von außen)
    self.timer = QTimer()
    self.timer.setInterval(4000)
    QObject.connect(self.timer, SIGNAL('timeout()'), self.execInstallCheck)
    QObject.connect(self.timer, SIGNAL('timeout()'), self.execRunningCheck)


  ## [static] Creates a new service object from a DOM node.
  @staticmethod
  def loadFromDomNode(root, parent = None):
    assert root.isElement()
    root = root.toElement()
    service = Service(parent)
    service.id = root.attribute('id')
    if not service.id: raise Exception('Service without ID')
    service.priority = root.attribute('priority')
    node = root.firstChild()
    while not node.isNull():
      if node.isElement() and node.toElement().tagName() == 'name':
        service.name = node.toElement().firstChild().toText().data()
      if node.isElement() and node.toElement().tagName() == 'description':
        service.description = node.toElement().firstChild().toText().data()
      if node.isElement() and node.toElement().tagName() == 'installcheck':
        service.installCheck  = node.toElement().firstChild().toText().data()
      if node.isElement() and node.toElement().tagName() == 'runningcheck':
        service.runningCheck = node.toElement().firstChild().toText().data()
      if node.isElement() and node.toElement().tagName() == 'startcommand':
        service.startCommand = node.toElement().firstChild().toText().data()
      if node.isElement() and node.toElement().tagName() == 'stopcommand':
        service.stopCommand = node.toElement().firstChild().toText().data()
      node = node.nextSibling()
    return service


  ## Outputs a DOM node containing all data of this service.
  def saveToDomNode(self, doc):
    node = doc.createElement('service')
    node.setAttribute('id', self.id)
    node.appendChild(mkTextElement(doc, 'name',         self.name))
    node.appendChild(mkTextElement(doc, 'description',  self.description))
    node.appendChild(mkTextElement(doc, 'installcheck', self.installCheck))
    node.appendChild(mkTextElement(doc, 'runningcheck', self.runningCheck))
    node.appendChild(mkTextElement(doc, 'startcommand', self.startCommand))
    node.appendChild(mkTextElement(doc, 'stopcommand',  self.stopCommand))
    return node


  ## Sets the polling interval for this service.
  # @param interval the interval in seconds.
  def setPollingInterval(self, interval):
    self.timer.setInterval(interval*1000)


  ## Starts polling with the interval set up by setPollingInterval().
  def startPolling(self):
    self.timer.start()
    self.timer.emit(SIGNAL('timeout()'))


  ## Stops polling...
  def stopPolling(self):
    self.timer.stop()


  ## Starts running check (threaded).
  @pyqtSlot()
  def execRunningCheck(self):
    proc = ShellProcess(self.runningCheck)
    if self.environment:
      proc.setProcessEnvironment(self.environment)
    QObject.connect(proc, SIGNAL('finished(int)'), partial(self.checkFinished, "runningcheck"))
    QObject.connect(proc, SIGNAL('error()'), partial(self.checkFinished, "runningcheck"))
    self.processes.add(proc)
    proc.start()


  ## Starts install check (threaded).
  @pyqtSlot()
  def execInstallCheck(self):
    proc = ShellProcess(self.installCheck)
    if self.environment:
      proc.setProcessEnvironment(self.environment)
    QObject.connect(proc, SIGNAL('finished(int)'), partial(self.checkFinished, "installcheck"))
    QObject.connect(proc, SIGNAL('error()'), partial(self.checkFinished, "installcheck"))
    self.processes.add(proc)
    proc.start()


  ## Starts this service (threaded).
  # Polling is suspended until command is finished.
  @pyqtSlot()
  def execStartCommand(self):
    self.stopPolling()
    self.killAllProcesses()
    self.setState( (self.state[0], 'starting') )
    cmd = self.startCommand
    print cmd
    proc = RootProcess(cmd)
    if self.environment:
      proc.setProcessEnvironment(self.environment)
    QObject.connect(proc, SIGNAL('finished(int)'), partial(self.commandFinished, "startcommand"))
    QObject.connect(proc, SIGNAL('error()'), partial(self.commandFinished, "startcommand"))
    self.processes.add(proc)
    proc.start()
    print "continuing"


  ## Stops this service (threaded).
  # Polling is suspended until command is finished.
  @pyqtSlot()
  def execStopCommand(self):
    self.stopPolling()
    self.killAllProcesses()
    self.setState( (self.state[0], 'stopping') )
    cmd = self.stopCommand
    print cmd
    proc = RootProcess(cmd)
    if self.environment:
      proc.setProcessEnvironment(self.environment)
    QObject.connect(proc, SIGNAL('finished()'), partial(self.commandFinished, "stopcommand"))
    QObject.connect(proc, SIGNAL('error()'), partial(self.commandFinished, "stopcommand"))
    self.processes.add(proc)
    proc.start()
    print "continuing"


  ## Updates service state and emit stateChanged() if necessary.
  def checkFinished(self, which):
    proc = self.sender()
    if which == "installcheck":
      newState = ('installed' if (proc.exitCode() == 0 and proc.readAll().length() > 0) else 'missing', self.state[1])
      self.setState(newState)
    if which == "runningcheck":
      newState = (self.state[0], 'running' if (proc.exitCode() == 0 and proc.readAll().length() > 0) else 'stopped')
      self.setState(newState)
    QTimer.singleShot(0, self.cleanupProcesses)


  ## [internal] Processes possible errors and continue checks
  def commandFinished(self, which):
    proc = self.sender()
    errorOutput = QString(proc.readAllStandardError())
    if errorOutput:
      QMessageBox.critical(None, self.name, self.tr('The command produced the following error:') + '\n' + errorOutput, QMessageBox.Ok)
    self.setState( (self.state[0], 'unknown') )
    self.startPolling()


  ## Shortcut for setting state and check if stateChanged() has to be emitted.
  def setState(self, newState):
    oldState = self.state
    self.state = newState
    if newState != oldState:
      self.emit(SIGNAL('stateChanged()'))



# Prozess-Verwaltungs-Funktionen ################################################################################


  ## Sets the environment for all processes.
  def setProcessEnvironment(self, env):
    #env.remove("SUDO")
    #env.insert("SUDO", "")
    self.environment = env


  ## Sets a sleep time to be appended to all commands.
  def setSleepTime(self, n):
    self.sleepTime = n


  ## [internal] Removes dead QProcesses.
  def cleanupProcesses(self):
    for proc in list(self.processes):
      if proc.state() == 0: self.processes.remove(proc)


  ## [internal] Kills all running Processes.
  def killAllProcesses(self):
    for proc in list(self.processes):
      proc.kill()
      self.processes.remove(proc)



## Shortcut for creating a DOM element containing text data.
def mkTextElement(doc, tagName, textData):
  node = doc.createElement(tagName)
  textNode = doc.createTextNode(textData)
  node.appendChild(textNode)
  return node