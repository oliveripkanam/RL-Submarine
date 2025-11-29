from cave_environment.environment import CaveEnvironment, Tile
from cave_environment.spritesheet import SpriteSheet
from Submarine import Submarine
import pygame
from pygame.locals import *

pygame.init()
DISPLAY_WIDTH, DISPLAY_HEIGHT = 60 * 16, 40 * 16
screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
canvas = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))

spritesheet = SpriteSheet("cave_environment/tileset.png")
font = pygame.font.Font(None, 25)

try:
    cave_env = CaveEnvironment("cave_environment/tileset_basic.csv", spritesheet)#
except Exception as e:
    print(f"Error loading cave environment: {e}")
    pygame.quit()
    exit()

submarine = Submarine(100, 100)

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

    canvas.fill((0, 128, 255))
    cave_env.draw(canvas)
    submarine.draw(canvas)
    battery_text = font.render(f'Battery: {submarine.battery}', True, (255, 255, 255))
    canvas.blit(battery_text, (10, 10))
    screen.blit(canvas, (0, 0))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()