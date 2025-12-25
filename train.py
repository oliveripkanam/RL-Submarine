import pygame
import pymunk
import numpy as np
import os
import glob
from src.cave_environment.environment import CaveEnvironment
from src.cave_environment.spritesheet import SpriteSheet
from src.entities.submarine import Submarine
from src.sonar.sensors import Sonar
from src.ai.agent import DoubleDQNAgent, VanillaDQNAgent

# Configuration
WATCH_MODE = True
LOAD_MODEL = True     # IMPORTANT: Set to "True" to continue training from previous save
NUM_EPISODES = 2000
MAX_STEPS = 4000
BATCH_SIZE = 64
EPSILON_START = 1.0
EPSILON_END = 0.01
EPSILON_DECAY = 0.999
TARGET_UPDATE = 1000
SAVE_INTERVAL = 50

# Initialize pygame
pygame.init()
screen = pygame.display.set_mode((1200, 800))
clock = pygame.time.Clock()
font = pygame.font.Font(None, 25)
hit_font = pygame.font.Font(None, 40)

def get_full_state(sonar_data, submarine):
    normalized_battery = submarine.battery / 300.0
    norm_vx = (submarine.vel_x + 8.0) / 16.0 
    norm_vy = (submarine.vel_y + 8.0) / 16.0
    
    return np.concatenate([
        sonar_data,
        [normalized_battery],
        [norm_vx, norm_vy]
    ])

def train():
    global WATCH_MODE
    
    # Auto-cleanup: If starting fresh, delete old models
    if not LOAD_MODEL:
        files = glob.glob("models/*.pth")
        for f in files:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Error deleting {f}: {e}")
        if files:
            print("Cleared previous models.")

    spritesheet = SpriteSheet("src/cave_environment/tileset.png")
    cave_env = CaveEnvironment("src/cave_environment/tileset_basic.csv", spritesheet)
    
    space = pymunk.Space()
    space.gravity = (0, 0)
    
    for tile in cave_env.environment_tiles:
        body = pymunk.Body(body_type=pymunk.Body.STATIC)
        body.position = (tile.rect.centerx, tile.rect.centery)
        shape = pymunk.Poly.create_box(body, (tile.rect.width, tile.rect.height))
        shape.filter = pymunk.ShapeFilter(group=1)
        space.add(body, shape)

    agent = VanillaDQNAgent(input_shape=19, num_actions=4)
    # agent = DoubleDQNAgent(input_shape=19, num_actions=4)
    epsilon = EPSILON_START
    episode_loss = np.full(NUM_EPISODES, None, dtype=np.float32)
    
    if LOAD_MODEL:
        try:
            agent.load("models/vanilla_dqn_submarine_final.pth")
            print("Successfully loaded existing model!")
            epsilon = 1
        except FileNotFoundError:
            print("No existing model found, starting fresh.")

    total_steps = 0

    print(f"Starting training on Device: {agent.device}")
    print("Press TAB to toggle Fast/Watch Mode. Press ESC to quit.")

    for episode in range(NUM_EPISODES):
        # Always start at x=100 (Full map)
        start_x = 100
        start_y = 300

        submarine = Submarine(start_x, start_y)
        submarine.battery = 300
        
        sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
        space.add(sonar_body)
        sonar = Sonar(space, sonar_body)
        
        current_observation = sonar.get_observation()
        state = get_full_state(current_observation, submarine)
        
        total_reward = 0
        done = False
        display_hit_msg = False
        total_loss = 0.0
        for step in range(MAX_STEPS):
            # Event handling (Throttled in fast mode)
            if WATCH_MODE or step % 100 == 0:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            pygame.quit()
                            return
                        if event.key == pygame.K_TAB:
                            WATCH_MODE = not WATCH_MODE
                            print(f"Watch Mode: {WATCH_MODE}")

            action = agent.select_action(state, epsilon)
            
            # Save previous position
            prev_x = submarine.true_x
            prev_y = submarine.true_y

            if action == 0: submarine.move_up()
            elif action == 1: submarine.move_down()
            elif action == 2: submarine.move_left()
            elif action == 3: submarine.move_right()
            
            submarine.update()
            sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
            
            next_observation = sonar.get_observation()
            next_state = get_full_state(next_observation, submarine)
            
            reward = -0.1
            
            # Encourage moving right (else it'll keep moving left)
            if action == 3: # Right
                reward += 0.05
            elif action == 2: # Left
                reward -= 0.05

            display_hit_msg = False
            
            hit_wall = False
            for reading in next_observation:
                if reading == 0: 
                    hit_wall = True
                    break
            
            if hit_wall:
                reward -= 10
                display_hit_msg = True
                
                # Hard revert: restore position to before the collision
                submarine.true_x = prev_x
                submarine.true_y = prev_y
                submarine.rect.x = int(prev_x)
                submarine.rect.y = int(prev_y)
                
                # Apply recoil velocity
                submarine.vel_x *= -0.5
                submarine.vel_y *= -0.5
                
                # Update physics body immediately
                sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
            
            if submarine.rect.right >= cave_env.environment_width - 10:
                reward += 100
                done = True
                print(f"Episode {episode}: REACHED GOAL!")

            if submarine.battery <= 0:
                reward -= 10
                done = True
            
            total_reward += reward

            agent.memory.push(state, action, reward, next_state, done)
            
            loss = agent.train_step(BATCH_SIZE)
            total_loss += loss if loss is not None else 0.0
            
            total_steps += 1
            if total_steps % TARGET_UPDATE == 0:
                agent.update_target_network()

            state = next_state

            if WATCH_MODE:
                canvas = pygame.Surface((cave_env.environment_width, cave_env.environment_height))
                canvas.fill((0, 128, 255))
                canvas.blit(cave_env.environment_surface, (0, 0))
                submarine.draw(canvas)
                sonar.draw(canvas, font)
                
                scale = min(1200 / cave_env.environment_width, 800 / cave_env.environment_height)
                new_size = (int(cave_env.environment_width * scale), int(cave_env.environment_height * scale))
                scaled = pygame.transform.smoothscale(canvas, new_size)
                
                screen.fill((0, 0, 0))
                screen.blit(scaled, ((1200 - new_size[0]) // 2, (800 - new_size[1]) // 2))
                
                # Info text
                info_text = f"Ep: {episode} | Step: {step} | Reward: {total_reward:.1f} | Eps: {epsilon:.2f}"
                batt_text = f"Battery: {submarine.battery:.1f}%"
                mode_text = "Press TAB for FAST MODE"
                
                screen.blit(font.render(info_text, True, (255, 255, 255)), (10, 10))
                screen.blit(font.render(batt_text, True, (255, 255, 0)), (10, 40))
                screen.blit(font.render(mode_text, True, (0, 255, 0)), (10, 70))

                if display_hit_msg:
                    hit_surf = hit_font.render("HIT WALL!", True, (255, 0, 0))
                    screen.blit(hit_surf, (1200 - 200, 50))
                
                pygame.display.flip()
                clock.tick(60)
            else:
                # In fast mode, pump events to keep window responsive but don't draw
                if step % 1000 == 0:
                    screen.fill((0, 0, 0))
                    msg = font.render(f"FAST MODE (Ep {episode}). Press TAB to Watch.", True, (0, 255, 0))
                    screen.blit(msg, (1200//2 - 150, 800//2))
                    pygame.display.flip()

            if done:
                break
        
        space.remove(sonar_body)
        
        epsilon = max(EPSILON_END, epsilon * EPSILON_DECAY)
        average_loss = total_loss / (step + 1)
        episode_loss[episode] = average_loss
        if episode % 10 == 0:
            print(f"Episode {episode}/{NUM_EPISODES} | Total Reward: {total_reward:.2f} | Epsilon: {epsilon:.2f} | Loss: {average_loss:.4f} ")

        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/vanilla_dqn_submarine_ep{episode}.pth")
            
    np.save("models/vanilla_dqn_training_loss.npy", episode_loss)
    agent.save("models/vanilla_dqn_submarine_final.pth")
    pygame.quit()

if __name__ == "__main__":
    train()
