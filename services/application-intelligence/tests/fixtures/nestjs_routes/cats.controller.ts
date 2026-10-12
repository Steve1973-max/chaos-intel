import { Controller, Get, Post } from '@nestjs/common';

@Controller('cats')
export class CatsController {
  @Get()
  findAll(): string {
    return 'This action returns all cats';
  }

  @Post(':id')
  create(): string {
    return 'This action creates a cat';
  }
}
