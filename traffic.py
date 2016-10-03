from flask import Flask, request
from flask_socketio import SocketIO, send, emit, join_room, leave_room, close_room, rooms

import os
import geojson
import codecs
import urllib2
from time import sleep, strftime, time
from geojson import FeatureCollection, Feature, Point

app = Flask(__name__)
app.config['SECRET_KEY'] = 'WRcFZLXh9vIUPPFPAxD8'
socketio = SocketIO(app)

url = 'http://sotoris.cz/DataSource/CityHack2015/vehiclesBrno.aspx'
routeLabelPairs = {
	470: 'x30',
	683: 'x83',
	891: 'A',
	384: 'x4',
	790: 'E50',
	182: 'P2',
	181: 'P1',
	381: 'x1',
	386: 'x6',
	100: 'L'
}
currentTraffic = {}
connectedClients = {}
updates = {'new': {}, 'update': {}, 'remove': {}}

@app.route('/')
def index():
	return "Working."

@socketio.on('connect')
def handle_new_client():
	global currentTraffic
	if (not currentTraffic):
		connectedClients[request.sid] = {}
		response = urllib2.urlopen(url)
		currentTraffic = initTraffic(geojson.loads(response.read()))
		print "STARTING WATCH TRAFFIC JOB"
		getVehicles()
	connectedClients[request.sid] = {"bbox": {}, "currentTraffic": {}}
	join_room(request.sid)
	print "%s CONNECTED" % (request.sid)

@socketio.on('disconnect')
def handle_disconnect():
	connectedClients.pop(request.sid, None)
	close_room(request.sid)
	if (not connectedClients):
		currentTraffic = {}
	print "%s DISCONNECTED" % (request.sid)

@socketio.on('initial bbox')
def first_bbox(latmax, lngmax, latmin, lngmin):
	connectedClients[request.sid]["bbox"] = {"latmax": latmax, "lngmax": lngmax, "latmin": latmin, "lngmin": lngmin}
	newTraffic = filterTrafficByBbox(connectedClients[request.sid]["bbox"])
	emit('initial traffic', newTraffic, json=True, room=request.sid)
	connectedClients[request.sid]["currentTraffic"] = newTraffic
	print "INITIAL TRAFFIC DATA TO %s, BBOX: %s, %s, %s, %s" % (request.sid, latmax, lngmax, latmin, lngmin)

@socketio.on('bbox')
def update_bbox(latmax, lngmax, latmin, lngmin):
	connectedClients[request.sid]["bbox"] = {"latmax": latmax, "lngmax": lngmax, "latmin": latmin, "lngmin": lngmin}
	update, newTraffic = getBboxUpdate(connectedClients[request.sid]["currentTraffic"], connectedClients[request.sid]["bbox"])
	emit('bbox change', update, json=True, room=request.sid)
	connectedClients[request.sid]["currentTraffic"] = newTraffic
	print "BBOX DATA TO %s, BBOX: %s, %s, %s, %s" % (request.sid, latmax, lngmax, latmin, lngmin)

#########################################################
#########################################################
######             DATA HANDLING NEXT              ######
#########################################################
#########################################################

def initTraffic(data):
	traffic = {}
	for vehicle in data:
		traffic[vehicle['vehicleId']] = vehicle
	return traffic

def getVehicles():
	while (connectedClients):
		start = time()
		response = urllib2.urlopen(url)
		data = geojson.loads(response.read())
		for vehicle in [item for item in data]:
			if ("latitude" not in vehicle or "longitude" not in vehicle):
				data.remove(vehicle)
			elif vehicle['route'] in routeLabelPairs:
				vehicle['routeLabel'], vehicle['route'] = routeLabelPairs[vehicle['route']], vehicle['route']
			elif 'routeLabel' not in vehicle:
				vehicle['routeLabel'], vehicle['route'] = vehicle['route'], vehicle['route']
		updates = checkUpdates(data)
		sendUpdates()
		print time() - start
		socketio.sleep(1)
	else:
		currentTraffic = {}
		print "NOBODY CONNECTED!"

def sendUpdates():
	# print "SENDING UPDATES!"
	for client in connectedClients.keys():
		if ("bbox" in connectedClients[client]):
			# send output only in the bbox
			newTraffic = filterTrafficByBbox(connectedClients[client]["bbox"])
			bboxUpdates = compareStates(connectedClients[client]["currentTraffic"], newTraffic)
			connectedClients[client]["currentTraffic"] = newTraffic
			if (bboxUpdates["new"] or bboxUpdates["update"] or bboxUpdates["remove"]):
				print "BBOX UPDATES to %s" % client, bboxUpdates
				emit('update', bboxUpdates, json=True, room=client)
		elif (updates["new"] or updates["update"] or updates["remove"]):
			print "UPDATES to %s" % client, updates
			emit('update', updates, json=True, room=client)

def checkUpdates(traffic):
	update = {'new': {}, 'update': {}, 'remove': {}}
	nextVehicles = [vehicle['vehicleId'] for vehicle in traffic]
	for vehicle in traffic:
		# print currentTraffic
		if vehicle['vehicleId'] in currentTraffic and vehicle != currentTraffic[vehicle['vehicleId']]:
			update['update'][vehicle['vehicleId']] = vehicle
			currentTraffic[vehicle['vehicleId']] = vehicle
		elif vehicle['vehicleId'] not in currentTraffic:
			update['new'][vehicle['vehicleId']] = vehicle
			currentTraffic[vehicle['vehicleId']] = vehicle
	for vehicle in currentTraffic.keys():
		if vehicle not in nextVehicles:
			update['remove'][vehicle] = currentTraffic[vehicle]
			currentTraffic.pop(vehicle, None)
	return update

def compareStates(old, new):
	update = {'new': {}, 'update': {}, 'remove': {}}
	for vehicle in new:
		if vehicle in old and new[vehicle] != old[vehicle]:
			update['update'][vehicle] = new[vehicle]
		elif vehicle not in old:
			update['new'][vehicle] = new[vehicle]
	for vehicle in old:
		if vehicle not in new:
			update['remove'][vehicle] = old[vehicle]
	return update

def filterTrafficByBbox(bbox):
	result = {}
	if (not bbox):
		return currentTraffic
	else:
		# print bbox
		for vehicle in currentTraffic.keys():
			# print bbox, currentTraffic[vehicle]["latitude"], currentTraffic[vehicle]["longitude"]
			if bbox["latmax"] > currentTraffic[vehicle]["latitude"] and bbox["latmin"] < currentTraffic[vehicle]["latitude"] and bbox["lngmax"] > currentTraffic[vehicle]["longitude"] and bbox["lngmin"] < currentTraffic[vehicle]["longitude"]:
				result[vehicle] = currentTraffic[vehicle]
		return result

def getBboxUpdate(oldTraffic, bbox):
	newTraffic = filterTrafficByBbox(bbox)
	update = compareStates(oldTraffic, newTraffic)
	return update, newTraffic

# def setProperty(name, source, target):
# 	if (name in source):
# 		target[name] = source[name]

# def buildGeoJson(data):
# 	features = []
# 	for item in data:
# 		props = {}
# 		point = None

# 		if ('latitude' in item and 'longitude' in item):
# 			point = Point(item['longitude'], item['latitude'])
# 		else:
# 			continue
# 		addProperty('vehicleId', item, props)
# 		addProperty('bearing', item, props)
# 		if item['route'] in routeLabelPairs:
# 			props['routeLabel'], props['routeId'] = routeLabelPairs[item['route']], item['route']
# 		elif 'routeLabel' in item:
# 			props['routeLabel'], props['routeId'] = item['routeLabel'], item['route']
# 		else:
# 			props['routeLabel'], props['routeId'] = item['route'], item['route']
# 		addProperty('course', item, props)
# 		addProperty('headsign', item, props)
# 		addProperty('consist', item, props)
# 		addProperty('lowFloor', item, props)
# 		features.append(Feature(geometry=point, properties=props))
# 	return geojson.dumps(FeatureCollection(features))

if __name__ == "__main__":
	socketio.run(app)
