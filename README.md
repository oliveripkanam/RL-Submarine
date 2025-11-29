## WIP

initial setup:
pip install pymunk pygame numpy

to run:
python sonar_test.py

controls:
WASD to move
1, 2, 3 to change environment shape

to integrate, just write:
    from sonar_sensors import Sonar
    my_sonar = Sonar(space, sub_body)
    state = my_sonar.get_observation()
