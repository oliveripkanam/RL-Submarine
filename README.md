## WIP

initial setup:
pip install pymunk pygame numpy

to run sonar test:
python sonar_test.py

to run main test:
python main_with_cave.py

controls:
WASD to move
1, 2, 3 to change environment shape

to integrate:
    from sonar_sensors import Sonar
    
    # Init (Before loop)
    my_sonar = Sonar(space, sub_body)
    
    # In Game Loop
    state = my_sonar.get_observation() # Get data for AI
    my_sonar.draw(screen, font)        # Draw lines on screen
