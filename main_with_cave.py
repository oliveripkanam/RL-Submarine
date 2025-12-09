from src.cave_environment.environment import CaveEnvironment, Tile
from src.cave_environment.spritesheet import SpriteSheet
from Submarine import Submarine
import pygame
import pymunk
from pygame.locals import *
from sonar_sensors import Sonar

pygame.init()
DISPLAY_WIDTH, DISPLAY_HEIGHT = 60 * 16, 40 * 16
screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
canvas = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))

spritesheet = SpriteSheet("src/cave_environment/tileset.png")
font = pygame.font.Font(None, 25)

# Map files list
map_files = [
    "src/cave_environment/tileset_basic.csv",
    # "src/cave_environment/tileset_jagged_narrow.csv", # Missing from merge
    # "src/cave_environment/tileset_right_angle.csv"    # Missing from merge
]
current_map_index = 0

def load_level(map_index):
    # Reset space
    new_space = pymunk.Space()
    actual_index = map_index
    
    try:
        # Safety check for index
        if map_index >= len(map_files):
            print(f"Map index {map_index} not found, defaulting to 0")
            actual_index = 0
            
        env = CaveEnvironment(map_files[actual_index], spritesheet)
        
        # Add walls
        for tile in env.environment_tiles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (tile.rect.centerx, tile.rect.centery)
            shape = pymunk.Poly.create_box(body, (16, 16))
            shape.elasticity = 0.0
            shape.friction = 0.0
            new_space.add(body, shape)
            
        return new_space, env, actual_index
        
    except Exception as e:
        print(f"Error loading map: {e}")
        return None, None, 0

# Initial load
space, cave_env, current_map_index = load_level(0)
if not space:
    pygame.quit()
    exit()

submarine = Submarine(100, 100)

# ghost body for sonar
sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
sonar_body.position = (submarine.true_x, submarine.true_y)
space.add(sonar_body)

my_sonar = Sonar(space, sonar_body, num_rays=16, max_range=200, agent_size=30)

running = True
clock = pygame.time.Clock()

while running:
    clock.tick(60)
    for event in pygame.event.get():
        if event.type == QUIT:
            running = False

        if event.type == KEYDOWN:
            if submarine.battery > 0:
                if event.key == K_UP: submarine.move_up()
                elif event.key == K_DOWN: submarine.move_down()
                elif event.key == K_LEFT: submarine.move_left()
                elif event.key == K_RIGHT: submarine.move_right()
            
            # Map switching
            new_space = None
            new_env = None
            
            if event.key == K_1:
                new_space, new_env, new_idx = load_level(0)
            elif event.key == K_2:
                new_space, new_env, new_idx = load_level(1)
            elif event.key == K_3:
                new_space, new_env, new_idx = load_level(2)
            
            if new_space:
                space = new_space
                cave_env = new_env
                current_map_index = new_idx
                my_sonar.space = space
                # Re-create ghost body since old space is gone
                sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                sonar_body.position = (100, 100)
                space.add(sonar_body)
                my_sonar.body = sonar_body # update sonar reference
                
                submarine.true_x, submarine.true_y = 100, 100
                submarine.battery = 100

    submarine.update()

    # sync sonar
    sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)

    # check for wall hits
    sensor_data = my_sonar.get_observation()
    hit_wall = False
    for reading in sensor_data:
        if reading == 0:
            hit_wall = True
            break
            
    if hit_wall:
        submarine.battery -= 10
        submarine.vel_x *= -0.5
        submarine.vel_y *= -0.5
        submarine.true_x += submarine.vel_x * 5
        submarine.true_y += submarine.vel_y * 5

    if submarine.battery < 0:
        submarine.battery = 0

    canvas.fill((0, 128, 255))
    if cave_env:
        cave_env.draw(canvas)
    submarine.draw(canvas)
    
    my_sonar.draw(canvas, font)
    
    # UI
    battery_text = font.render(f'Battery: {submarine.battery} | Map: {map_files[current_map_index]}', True, (255, 255, 255))
    # controls text
    controls_text = font.render('Arrows: Move | 1,2,3: Change Map', True, (255, 255, 0))
    
    canvas.blit(battery_text, (10, 10))
    canvas.blit(controls_text, (10, 30))
    screen.blit(canvas, (0, 0))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
