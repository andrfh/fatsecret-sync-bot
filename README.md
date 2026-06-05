# **Fatsecret-sync-bot**
The service based on telegram chat that allows you to determine the number of calories in by image and synchronizat the result with fatsecret app. 

## The problem
It is difficult for user to serach ingridients separately and count callories manually. 

## The solution
A user uploads a photo of food to a telegram-chat and the AI calculates the approximate number of callories and proteins/fats/carbohydrates. Then it automaticly synchronizates the result in user`s fatsecret application. 

## Target Audience
People who track their diet, count calories and want to log their meals faster and easily. 

## Key feauters
- Food recognition from photos
- Automatic calculation of proteins/fats/carbohydrates
- Approve the results before synchronizate
- Option to manually adjust results
- Sync food with FatSecret

## MVP
In the first version, the service sholud be able to:
- accept food photos via Telegram
- send photos for recognition
- return an approximate description of the food and its nutritional value
- allow the user to confirm the result
- sync confirmed meals with FatSecret

## Basic user scenario

1. The user opens the Telegram bot.
2. The user logs in to FatSecret.
3. Sends a photo of a meal.
4. The bot analyzes the photo.
5. The bot displays the suggested dish and its nutritional value.
6. The user confirms or edits the result.
7. The bot sends the data to FatSecret.
8. The user receives synchronization confirmation.


## External Services

- Telegram Bot API.
- FatSecret API.
- openai model for computer vision.
