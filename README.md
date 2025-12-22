## WIP

initial setup:
pip install pymunk pygame numpy

to run sonar test:
python src/sonar/test.py

to run main test:
python main.py

controls:
Arrows to move
1-7 to change maps

to integrate:
    from src.sonar.sensors import Sonar
    
    # Init (Before loop)
    my_sonar = Sonar(space, sub_body)
    
    # In Game Loop
    state = my_sonar.get_observation() # Get data for AI
    my_sonar.draw(screen, font)        # Draw lines on screen
