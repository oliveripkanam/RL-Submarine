from cave_environment.environment import CaveEnvironment, Tile
from cave_environment.spritesheet import SpriteSheet
import pygame

pygame.init()
DISPLAY_WIDTH, DISPLAY_HEIGHT = 60 * 16, 40 * 16
screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
canvas = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))

spritesheet = SpriteSheet("cave_environment/tileset.png")
player_img = spritesheet.get_sprite("middle")
player_rect = player_img.get_rect()
try:
    cave_env = CaveEnvironment("cave_environment/tileset_basic.csv", spritesheet)#
    player_rect.x, player_rect.y = cave_env.start_x, cave_env.start_y
except Exception as e:
    print(f"Error loading cave environment: {e}")
    pygame.quit()
    exit()

running = True
clock = pygame.time.Clock()
while running:
    clock.tick(60)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    canvas.fill((0, 128, 255))
    cave_env.draw(canvas)
    canvas.blit(player_img, player_rect)
    screen.blit(canvas, (0, 0))
    pygame.display.flip()