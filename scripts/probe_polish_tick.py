import sys
from test_polish_lua import side, FAKES, STATE, POLISH  # reuse the test's exact setup
s = side("sp")
s.run("car = spawnCar(1, 3); car.engine = true; car.rpm = 820; car.x = 100; car.y = 100")
s.run("CELL.list.list = nil")
s.run("CELL_LIST = {car}")
try:
    s.run("TICK(31)")
    print("OK: tick ran; started:", s.eval("HondaCRVGen1.Polish.cars[car] ~= nil"))
except Exception as e:
    print("ERROR:", str(e)[:600])
