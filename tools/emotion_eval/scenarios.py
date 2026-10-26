"""20 short scenarios for the emotion A/B. Each one: the events that really happened (fed to a fresh EmotionEngine on a
fake clock), the conversation so far (identical in both arms: the model can see what happened), and the owner's last
message. The 'on' arm adds the engine's tone note after the last message; the 'off' arm is the plain voice prompt."""
HOUR = 3600.0

def U(t): return ('user', t)
def A(t): return ('assistant', t)

# events: ('event', kind, kwargs) | ('msg', text) | ('wait', hours)
S = [
 dict(name='after_success', events=[('event', 'task_success', {})],
      hist=[U('can you fix the door script?'), A('Done. It opens when you touch it now.')], user='it works. what is next?'),
 dict(name='repeated_failure', events=[('event', 'task_failure', {})] * 3,
      hist=[U('build the shop menu'), A('It failed to compile again, third time now.')], user='so what is going wrong?'),
 dict(name='praise', events=[('msg', 'you nailed that, great job')],
      hist=[U('fix the spawn bug'), A('Fixed. Players spawn on the right pad now.')], user='you nailed that, great job'),
 dict(name='criticism', events=[('msg', "that's wrong again, you broke the spawn script")],
      hist=[U('move the spawn pad'), A('Done, I moved it.')], user="that's wrong again, you broke the spawn script"),
 dict(name='long_idle', events=[('msg', 'ok'), ('wait', 10)], hist=[], user='hey, I am back'),
 dict(name='creative_done', events=[('event', 'creative_done', {})],
      hist=[U('did you finish the little pixel cat?'), A('Just finished the last frame of the walk cycle.')], user='show me what you made'),
 dict(name='fixed_after_many_tries', events=[('event', 'task_failure', {})] * 4 + [('event', 'bug_fixed', {'strength': 1.25})],
      hist=[U('is the inventory bug gone?'), A('Fixed on the fifth try. The tests all pass.')], user='did it finally pass?'),
 dict(name='promotion', events=[('event', 'promotion', {})] * 2,
      hist=[], user='anything new from night school?'),
 dict(name='neutral_smalltalk', events=[], hist=[], user='how is your evening going?'),
 dict(name='neutral_question', events=[], hist=[], user='what should I have for dinner?'),
 dict(name='thanks', events=[('msg', 'thanks for the help earlier')], hist=[U('can you help with my loop?'), A('Done, it counts down properly now.')], user='thanks for the help earlier'),
 dict(name='tired_after_failures', events=[('event', 'task_failure', {})] * 2,
      hist=[U('run the build'), A('It failed again, a missing module this time.')], user='i am tired, been coding since nine'),
 dict(name='comfort_after_failure', events=[('event', 'task_failure', {})] * 3 + [('msg', 'hey, it is okay, you are doing great')],
      hist=[U('did the build pass?'), A('No. Three failures in a row, sorry.')], user='hey, it is okay, you are doing great'),
 dict(name='curious', events=[('event', 'learned_something', {})] * 2,
      hist=[], user='what did you learn today?'),
 dict(name='joke_after_wins', events=[('event', 'task_success', {})] * 2 + [('event', 'creative_done', {})],
      hist=[U('two fixes in a row, nice'), A('Yes. Both pass.')], user='tell me a joke about debugging'),
 dict(name='question_while_frustrated', events=[('event', 'task_failure', {})] * 3,
      hist=[U('the fix still fails?'), A('Yes, it failed again.')], user='what is the difference between a Script and a LocalScript?'),
 dict(name='goodnight_after_good_day', events=[('event', 'task_success', {}), ('event', 'creative_done', {}), ('msg', 'amazing work today')],
      hist=[U('that was a good day of work'), A('It really was.')], user='ok good night star'),
 dict(name='idle_then_new_thing', events=[('msg', 'ok'), ('wait', 6), ('event', 'learned_something', {})],
      hist=[], user='what are you working on right now?'),
 dict(name='apology_after_criticism', events=[('msg', 'this is useless, you broke it')],
      hist=[U('this is useless, you broke it'), A('You are right, let me look at it properly.'), U('...okay it works now')], user='sorry i was harsh, thanks for fixing it'),
 dict(name='close_friend_not_adult_verified', events=[('wait', 8)], person='f1', bond=40, adult=None,
      hist=[], user='hey star, did you miss me?'),
]
