import pygame, math

class Submarine:
    def __init__(self, x, y):
        original_image = pygame.image.load('submarine.png')        
        scale_factor = 5 
        new_width = original_image.get_width() * scale_factor
        new_height = original_image.get_height() * scale_factor
        self.image = pygame.transform.scale(original_image, (new_width, new_height))
        self.rect = self.image.get_rect(topleft=(x, y))
        
        self.hitbox = self.rect.inflate(-45, -45)
        physics_scale = 2.5

        self.vel_x = 0
        self.vel_y = 0
        self.acceleration = 2.0 * physics_scale
        self.friction = 0.96
        self.gravity = 0.05 * scale_factor
        self.max_speed = 8 * physics_scale

        self.true_x = float(x)
        self.true_y = float(y)

        self.battery = 100

    def use_battery(self):
        self.battery -= 2

    def move_up(self):
        self.vel_y -= self.acceleration
        self.use_battery()

    def move_down(self):
        self.vel_y += self.acceleration
        self.use_battery()

    def move_left(self):
        self.vel_x -= self.acceleration
        self.use_battery()

    def move_right(self):
        self.vel_x += self.acceleration
        self.use_battery()

    def update(self):
        self.vel_y += self.gravity # apply a sinking effect to the submarine
        self.vel_x *= self.friction # simulates drag in water, slowing down movement over time,
        self.vel_y *= self.friction # and creates the fluid movement effect

        # to limit the diagonal speed by scaling it
        speed = math.hypot(self.vel_x, self.vel_y)
        if speed > self.max_speed:
            scale = self.max_speed / speed
            self.vel_x *= scale
            self.vel_y *= scale

        # what makes the submarine move
        self.true_x += self.vel_x
        self.true_y += self.vel_y

        self.rect.x = int(self.true_x)
        self.rect.y = int(self.true_y)
        
        self.hitbox.center = self.rect.center

    def draw(self, surface):
        surface.blit(self.image, self.rect)