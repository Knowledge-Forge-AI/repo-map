import { Body, Controller, Get, Injectable, Module, Param, Post } from "@nestjs/common";

@Module({ imports: [UsersModule], controllers: [AppController], providers: [AppService] })
export class AppModule {}

@Controller("users")
export class UsersController {
  @Get(":id")
  getUser(@Param("id") id: string) {}

  @Post()
  createUser(@Body() body: unknown) {}
}

@Injectable()
export class AppService {}
