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

space = pymunk.Space()

try:
    cave_env = CaveEnvironment("src/cave_environment/tileset_basic.csv", spritesheet)
    
    # convert tiles to pymunk walls
    for tile in cave_env.environment_tiles:
        body = pymunk.Body(body_type=pymunk.Body.STATIC)
        body.position = (tile.rect.centerx, tile.rect.centery)
        
        shape = pymunk.Poly.create_box(body, (16, 16))
        shape.elasticity = 0.0
        shape.friction = 0.0
        space.add(body, shape)

except Exception as e:
    print(f"Error loading cave environment: {e}")
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

        if event.type == KEYDOWN and submarine.battery > 0:
            if event.key == K_UP:
                submarine.move_up()
            elif event.key == K_DOWN:
                submarine.move_down()
            elif event.key == K_LEFT:
                submarine.move_left()
            elif event.key == K_RIGHT:
                submarine.move_right()

    submarine.update()

    # sync sonar
    sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)

    canvas.fill((0, 128, 255))
    cave_env.draw(canvas)
    submarine.draw(canvas)
    
    my_sonar.draw(canvas, font)
    
    battery_text = font.render(f'Battery: {submarine.battery}', True, (255, 255, 255))
    canvas.blit(battery_text, (10, 10))
    screen.blit(canvas, (0, 0))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()